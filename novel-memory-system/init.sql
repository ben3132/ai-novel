-- =============================================================================
-- novel-memory-system · init.sql
-- PostgreSQL 16 + pgvector 小说记忆库 Schema
--
-- 设计要点（对应计划 v1.1）：
--   1. chapters/events 按月 RANGE 分区，分区键进入复合主键：
--        chapters PK (id, created_at)；events PK (id, timestamp)
--   2. events 携带 chapter_created_at，与 chapter_id 构成对
--        chapters(id, created_at) 的可分区裁剪引用（双路径触发器，见 2.3）
--   3. 不做 DEFAULT 分区；用 ensure_month_partition() 幂等建分区并同步建 HNSW
--   4. HNSW 逐子表建立（m=16, ef_construction=64）
--   5. update_embedding() 列级触发器：文本字段变更时把 embedding 置 NULL，
--        回填语句只 SET embedding → 不触发 → 无死循环
--
-- 注意：本文件只在 docker 数据卷【首次初始化】时自动执行；
--       修改后需 docker compose down -v 重灌 或 psql -f init.sql 手动执行。
-- =============================================================================

-- 扩展（pgvector 镜像已内置，此处幂等声明）
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- 1. 枚举类型
-- =============================================================================
CREATE TYPE event_type AS ENUM (
    'combat', 'dialogue', 'travel', 'discovery', 'conflict',
    'plot_twist', 'emotion', 'relationship', 'milestone', 'other'
);
COMMENT ON TYPE event_type IS '事件类型枚举：战斗/对话/移动/发现/冲突/转折/情感/关系/里程碑/其他';

CREATE TYPE ws_source AS ENUM ('original', 'enriched', 'user_confirmed');
COMMENT ON TYPE ws_source IS '世界设定信息来源：原文提取/联网补全/人工确认';

CREATE TYPE thread_status AS ENUM ('open', 'progressing', 'resolved', 'abandoned');
COMMENT ON TYPE thread_status IS '剧情线状态：开启/推进中/已了结/已废弃';

-- =============================================================================
-- 2. 序列（分区表不使用 IDENTITY，用共享序列 DEFAULT，规避分区身份列兼容风险）
-- =============================================================================
CREATE SEQUENCE chapters_id_seq;
CREATE SEQUENCE events_id_seq;

-- =============================================================================
-- 3. 表定义
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 3.1 chapters：章节（按 created_at 月分区）
-- -----------------------------------------------------------------------------
CREATE TABLE chapters (
    id          bigint          NOT NULL DEFAULT nextval('chapters_id_seq'),
    number      int             NOT NULL,                 -- 章节号（应用层幂等唯一）
    title       text            NOT NULL,                 -- 章节标题
    content     text            NOT NULL,                 -- 章节全文（存量稿件原文）
    summary     text,                                     -- 章节摘要（LLM 提取）
    embedding   vector(1536),                             -- 全文语义向量；文本变更时被触发器置 NULL 待重生成
    created_at  timestamptz     NOT NULL,                 -- 章节时间（分区键，写入后只读）
    PRIMARY KEY (id, created_at)                          -- 分区键必须进入主键
) PARTITION BY RANGE (created_at);

COMMENT ON TABLE  chapters            IS '章节表：按 created_at 月分区存储章节原文/摘要/向量';
COMMENT ON COLUMN chapters.id          IS '章节主键（共享序列生成，与 created_at 构成复合主键）';
COMMENT ON COLUMN chapters.number      IS '章节号，自 1 递增；由 ETL 幂等预检保证不重复（分区表无法建 number 唯一约束）';
COMMENT ON COLUMN chapters.title       IS '章节标题';
COMMENT ON COLUMN chapters.content     IS '章节全文（原稿 Markdown 正文）';
COMMENT ON COLUMN chapters.summary     IS '章节摘要（LLM 结构化提取产物）';
COMMENT ON COLUMN chapters.embedding   IS '语义向量(1536 维)；content/summary/title 更新时被触发器置 NULL，需重新生成';
COMMENT ON COLUMN chapters.created_at  IS '章节时间（分区键）。存量稿件导入时按 ETL_TIME_BASE/SPAN 计算，写入后只读';

-- 高频查询索引：按章节号取最近摘要（父表 btree 自动递归到各分区子表）
CREATE INDEX idx_chapters_number ON chapters (number);

-- -----------------------------------------------------------------------------
-- 3.2 characters：角色（非分区）
-- -----------------------------------------------------------------------------
CREATE TABLE characters (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                     text    NOT NULL,            -- 角色名
    current_state            jsonb,                       -- 最新状态快照（LLM 维护）
    first_appear_chapter_id  bigint,                      -- 首次登场章节 id（应用层引用 chapters.id）
    embedding                vector(1536)                 -- 角色名+状态的语义向量
);
COMMENT ON TABLE  characters                          IS '角色表：角色当前状态快照与语义向量（非分区）';
COMMENT ON COLUMN characters.id                       IS '角色主键';
COMMENT ON COLUMN characters.name                     IS '角色名（应唯一，检索时按名定位）';
COMMENT ON COLUMN characters.current_state            IS '最新状态快照 jsonb，如 {健康, 位置, 人际关系, 目标}';
COMMENT ON COLUMN characters.first_appear_chapter_id  IS '首次登场章节 id（指向 chapters，应用层引用）';
COMMENT ON COLUMN characters.embedding                IS '角色语义向量(1536)；name/current_state 更新时被触发器置 NULL';

-- 非分区表常规 HNSW 索引
CREATE INDEX idx_characters_embedding ON characters USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- 角色名唯一：ETL 按 name UPSERT 维护 current_state 最新快照，防重跑/并发产生同名脏行
CREATE UNIQUE INDEX idx_characters_name ON characters (name);

-- -----------------------------------------------------------------------------
-- 3.3 world_settings：世界设定（非分区）
-- -----------------------------------------------------------------------------
CREATE TABLE world_settings (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category         text    NOT NULL,                   -- 类别：地理/历史/文化/力量体系/组织/…（enrich 针对 地理/历史/文化）
    key              text    NOT NULL,                   -- 设定键名，如 "帝国首都_名称"
    value            text    NOT NULL,                   -- 设定值（原文/补全/人工确认后的最终文本）
    source           ws_source NOT NULL DEFAULT 'original',
    confidence_score float   NOT NULL DEFAULT 0.7,
    embedding        vector(1536),
    CONSTRAINT chk_ws_confidence CHECK (confidence_score >= 0 AND confidence_score <= 1)
);
COMMENT ON TABLE  world_settings                  IS '世界设定表：长期设定条目（非分区）';
COMMENT ON COLUMN world_settings.id               IS '设定主键';
COMMENT ON COLUMN world_settings.category         IS '设定类别（地理/历史/文化/力量体系/组织等）；地理/历史/文化且置信度<0.7 时触发联网补全';
COMMENT ON COLUMN world_settings.key              IS '设定键名（同 category 内应唯一）';
COMMENT ON COLUMN world_settings.value            IS '设定值：最终采纳文本';
COMMENT ON COLUMN world_settings.source           IS '来源：original=原文提取(默认) / enriched=联网补全 / user_confirmed=人工确认';
COMMENT ON COLUMN world_settings.confidence_score IS '置信度 0-1，默认 0.7；<0.7 且 category∈{地理,历史,文化} 时进入联网补全';
COMMENT ON COLUMN world_settings.embedding        IS '设定语义向量(1536)；key/value 更新时被触发器置 NULL';

CREATE INDEX idx_world_settings_embedding ON world_settings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
-- (category, key) 唯一：ETL 按此 UPSERT，防止同一条设定被重跑/并发重复写入
CREATE UNIQUE INDEX idx_world_settings_category_key ON world_settings (category, key);

-- -----------------------------------------------------------------------------
-- 3.4 events：事件（按 timestamp 月分区）
-- -----------------------------------------------------------------------------
CREATE TABLE events (
    id                   bigint        NOT NULL DEFAULT nextval('events_id_seq'),
    chapter_id           bigint        NOT NULL,         -- 所属章节 id
    chapter_created_at   timestamptz   NOT NULL,         -- 【v1.1】引用章节的 created_at，
                                                         --  与 chapter_id 共同指向 chapters(id, created_at)：
                                                         --  (a) 触发器做可分区裁剪的完整性校验
                                                         --  (b) JOIN chapters 时携带分区键实现剪枝
    type                 event_type    NOT NULL,         -- 事件类型（枚举）
    description          text          NOT NULL,         -- 事件描述（LLM 提取）
    related_characters   jsonb         NOT NULL DEFAULT '[]',  -- [{"character_id":..,"role":".."}] 仅存 id+角色
    timestamp            timestamptz   NOT NULL,         -- 事件时间（分区键，写入后只读）
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

COMMENT ON TABLE  events                       IS '事件表：按 timestamp 月分区记录情节事件';
COMMENT ON COLUMN events.id                    IS '事件主键（共享序列，与 timestamp 构成复合主键）';
COMMENT ON COLUMN events.chapter_id            IS '所属章节 id（无真实外键，完整性由 trg_events_chapter 双路径触发器保证）';
COMMENT ON COLUMN events.chapter_created_at    IS '所属章节的 created_at（引用列）；与 chapter_id 组成复合引用，保证校验/JOIN 可分区裁剪';
COMMENT ON COLUMN events.type                  IS '事件类型（combat/dialogue/travel/discovery/conflict/plot_twist/emotion/relationship/milestone/other）';
COMMENT ON COLUMN events.description           IS '事件描述';
COMMENT ON COLUMN events.related_characters    IS '关联角色列表 [{"character_id":1,"role":"主角"}]，character_id 指向 characters.id（应用层）';
COMMENT ON COLUMN events.timestamp             IS '事件时间（分区键）。由 ETL 按章内事件数均布于章节时间区间，写入后只读';

-- 高频复合索引：按章节查事件、按事件类型过滤（父表 btree 递归到子表）
CREATE INDEX idx_events_chapter_type ON events (chapter_id, type);
-- JOIN/校验剪枝辅助：复合引用列加速
CREATE INDEX idx_events_chapter_created ON events (chapter_id, chapter_created_at);

-- -----------------------------------------------------------------------------
-- 3.5 plot_threads：剧情线（非分区）
-- -----------------------------------------------------------------------------
CREATE TABLE plot_threads (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title          text   NOT NULL,                      -- 剧情线标题（伏笔/线索/主线）
    status         thread_status NOT NULL DEFAULT 'open',
    related_events jsonb  NOT NULL DEFAULT '[]',         -- [{"event_id":..,"relation":".."}] 关联事件
    priority       int    NOT NULL DEFAULT 0             -- 优先级（越大越靠前）
);
COMMENT ON TABLE  plot_threads                  IS '剧情线表：中程记忆（伏笔/线索/主线），resolved 表示已了结';
COMMENT ON COLUMN plot_threads.id               IS '剧情线主键';
COMMENT ON COLUMN plot_threads.title            IS '剧情线标题';
COMMENT ON COLUMN plot_threads.status           IS '状态：open=开启/progressing=推进中/resolved=已了结/abandoned=已废弃；get_chapter_context 自动过滤 resolved/abandoned';
COMMENT ON COLUMN plot_threads.related_events   IS '关联事件 [{"event_id":1,"relation":"铺垫"}]，event_id 指向 events（应用层）';
COMMENT ON COLUMN plot_threads.priority         IS '优先级（排序用，数值大靠前）';

-- 剧情线按状态+优先级排序
CREATE INDEX idx_plot_threads_status_priority ON plot_threads (status, priority DESC);
-- 标题唯一：ETL 按 title UPSERT，防止同一剧情线被重跑/并发重复写入
CREATE UNIQUE INDEX idx_plot_threads_title ON plot_threads (title);

-- =============================================================================
-- 4. 动态建分区函数（幂等：建分区即建 HNSW 索引）
-- =============================================================================
CREATE FUNCTION ensure_month_partition(parent text, ts timestamptz) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    m       text := to_char(date_trunc('month', ts), 'YYYY_MM');
    start_m timestamptz;
    end_m   timestamptz;
    has_emb boolean;
BEGIN
    start_m := date_trunc('month', ts);
    end_m   := start_m + interval '1 month';
    -- 建子表（存在则跳过）；名称形如 chapters_2026_09
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I
         FOR VALUES FROM (%L) TO (%L)',
        parent || '_' || m, parent, start_m, end_m
    );
    -- 仅当父表含 embedding 列（chapters）时才建 HNSW；events 无向量列，跳过
    EXECUTE format(
        'SELECT EXISTS (
             SELECT 1 FROM pg_attribute a
             JOIN pg_class c ON c.oid = a.attrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = ''public'' AND c.relname = %L
               AND a.attname = ''embedding'' AND NOT a.attisdropped
         )',
        parent || '_' || m
    ) INTO has_emb;
    IF has_emb THEN
        -- 同步建该子表 HNSW（幂等）；索引名形如 chapters_2026_09_emb
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I USING hnsw (embedding vector_cosine_ops)
             WITH (m = 16, ef_construction = 64)',
            parent || '_' || m || '_emb', parent || '_' || m
        );
    END IF;
    RETURN parent || '_' || m;
END $$;
COMMENT ON FUNCTION ensure_month_partition(text, timestamptz) IS '幂等创建月分区子表并同步建 HNSW 索引；init.sql 预建与 ETL 动态建分区共用';

-- =============================================================================
-- 5. 【v1.1】双路径参照完整性触发器（替代真实外键）
--    快路径：带分区裁剪，命中 chapters 复合 PK → 单分区 O(1)，写入延迟与分区数无关
--    兜底路径：仅快路径未命中时全分区检查，用于区分两种错误，不影响正常写入性能
-- =============================================================================
CREATE FUNCTION check_events_chapter() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_id_exists boolean;
BEGIN
    -- 快路径：复合键等值查询 → PG 按 created_at 裁剪到唯一子表，走子表 PK 索引
    IF EXISTS (
        SELECT 1 FROM chapters
        WHERE id = NEW.chapter_id AND created_at = NEW.chapter_created_at
    ) THEN
        RETURN NEW;
    END IF;

    -- 兜底/诊断路径（仅在快路径未命中时执行，正常写入不走这里）
    SELECT EXISTS (SELECT 1 FROM chapters WHERE id = NEW.chapter_id) INTO v_id_exists;
    IF NOT v_id_exists THEN
        RAISE EXCEPTION 'chapter_id % 不存在于 chapters', NEW.chapter_id
            USING ERRCODE = '23503';
    END IF;
    RAISE EXCEPTION 'chapter_id % 存在但 created_at % 不匹配（章节时间数据不一致）',
        NEW.chapter_id, NEW.chapter_created_at
        USING ERRCODE = '23503';
END $$;
COMMENT ON FUNCTION check_events_chapter() IS 'events 参照完整性双路径校验：快路径按 (chapter_id, chapter_created_at) 复合键分区裁剪命中；未命中才走全分区诊断路径';

CREATE TRIGGER trg_events_chapter
    BEFORE INSERT OR UPDATE OF chapter_id, chapter_created_at ON events
    FOR EACH ROW EXECUTE FUNCTION check_events_chapter();

-- =============================================================================
-- 6. update_embedding()：文本字段变更 → embedding 置 NULL（标记需重生成）
--    列级触发器：仅当文本列出现在 UPDATE SET 中才触发；
--    ETL 回填 UPDATE ... SET embedding=... 不含文本列 → 不触发 → 不回填即被清空
-- =============================================================================
CREATE FUNCTION update_embedding() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    n jsonb := to_jsonb(NEW);
    o jsonb := to_jsonb(OLD);
BEGIN
    -- 仅当被跟踪的文本/状态列【实际变化】时才清空 embedding（同值 UPSERT 不清，
    -- 避免无谓重复回填）。用 to_jsonb + ? 键判断，避免跨表 NEW.xxx 静态列引用报错
    -- （characters/world_settings 无 content/title 等列）。
    IF (n ? 'title'         AND n->>'title'         IS DISTINCT FROM o->>'title')
    OR (n ? 'summary'       AND n->>'summary'       IS DISTINCT FROM o->>'summary')
    OR (n ? 'content'       AND n->>'content'       IS DISTINCT FROM o->>'content')
    OR (n ? 'name'          AND n->>'name'          IS DISTINCT FROM o->>'name')
    OR (n ? 'current_state' AND n->>'current_state' IS DISTINCT FROM o->>'current_state')
    OR (n ? 'key'           AND n->>'key'           IS DISTINCT FROM o->>'key')
    OR (n ? 'value'         AND n->>'value'         IS DISTINCT FROM o->>'value') THEN
        NEW.embedding := NULL;
    END IF;
    RETURN NEW;
END $$;
COMMENT ON FUNCTION update_embedding() IS '内容字段变更时清空 embedding 标记需重生成；嵌入回填语句只改 embedding 列故不触发，避免死循环';

CREATE TRIGGER trg_chapters_embedding
    BEFORE UPDATE OF content, summary, title ON chapters
    FOR EACH ROW EXECUTE FUNCTION update_embedding();
CREATE TRIGGER trg_characters_embedding
    BEFORE UPDATE OF name, current_state ON characters
    FOR EACH ROW EXECUTE FUNCTION update_embedding();
CREATE TRIGGER trg_world_settings_embedding
    BEFORE UPDATE OF key, value ON world_settings
    FOR EACH ROW EXECUTE FUNCTION update_embedding();

-- =============================================================================
-- 7. 预建分区：chapters/events 各预建 当前月 + 后 2 个月 子表
--    （ETL 处理更早/更晚月份时由 ensure_month_partition 自动补建）
-- =============================================================================
SELECT ensure_month_partition('chapters', now() + i * interval '1 month') FROM generate_series(0, 2) AS i;
SELECT ensure_month_partition('events',    now() + i * interval '1 month') FROM generate_series(0, 2) AS i;

-- =============================================================================
-- 8. 自检（可手动执行确认初始化成功）
--   SELECT count(*) FROM chapters;              -- 预建子表会显示行数=0
--   SELECT tablename FROM pg_tables WHERE tablename LIKE 'chapters_%' ORDER BY 1;
--   \d+ chapters  查看分区与索引
-- =============================================================================
