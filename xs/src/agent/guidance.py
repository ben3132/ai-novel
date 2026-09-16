"""Machine-readable operating contract for an Agent loading this toolkit."""

from __future__ import annotations


def get_agent_guidance() -> dict:
    return {
        "schema_version": 3,
        "project_role": "agent_guided_evidence_toolkit",
        "embedded_llm_required": False,
        "decision_owner": "connected_agent",
        "agent_responsibilities": [
            "interpret_research_goal", "discover_work_tree_and_continuities",
            "discover_dynamic_sources", "verify_publisher_and_propose_trust_level",
            "choose_technical_collector", "decide_coverage_and_next_actions",
        ],
        "implemented_agent_operations": [
            "get_agent_guidance", "initialize_ip", "get_research_state",
            "get_research_status", "register_work", "register_source",
            "update_source_status", "save_claim_candidate", "next_actions",
            "list_works", "get_corpus_status", "get_entity", "search_evidence", "search_hybrid",
        ],
        "cli_commands": {
            "collect": "run_l1_collect.py",
            "extract_pdf_pages": "run_extract_pdf.py",
            "segment": "run_process.py",
            "build_windows": "run_build_windows.py",
            "build_database": "run_build_index.py",
            "build_vector_index": "build_ip_vector_index.py",
        },
        "agent_tasks_not_api_operations": [
            "discover_work_tree", "discover_sources", "choose_collector",
            "cross_check_l1", "assess_coverage_and_gaps",
        ],
        "not_implemented": [
            "automatic_web_source_discovery", "automatic_work_tree_discovery",
            "single_command_end_to_end_pipeline", "coverage_report_operation",
            "autonomous_research_loop", "pdf_page_ocr_fallback",
            "structured_xml_fdx_extraction",
        ],
        "autonomy": {
            "continue_without_confirmation": ["local_read_only", "reversible", "low_cost", "in_scope_research"],
            "pause_for": ["credentials_or_user_files", "paid_access", "captcha_or_login", "destructive_action", "access_control_bypass", "material_scope_choice"],
        },
        "trust_rules": {
            "1": "official_primary",
            "11": "third_party_transcription_requires_l1_cross_check",
            "2": "cited_fan_reference", "3": "secondary_community",
            "4": "collect_as_lead_only_excluded_from_reasoning",
        },
        "completion_rules": {
            "pipeline_complete_is_not_ip_complete": True,
            "ip_complete_requires": ["work_tree_coverage", "continuity_coverage", "source_type_coverage", "explicit_gap_list"],
            "source_count_field": "source_artifact_count",
            "do_not_call_derived_pages_sources": True,
        },
        "documentation": ["AGENTS.md", "docs/AGENT_INTEGRATION_GUIDE.md", "docs/IP_RESEARCH_PROTOCOL.md", "docs/agent_query_api.md"],
        "next_actions_semantics": "advisory tasks, not operation names; inspect kind and required_commands",
        "warning": "Do not infer implementation from workflow prose; only implemented_agent_operations are callable through run_ip_agent.py.",
    }
