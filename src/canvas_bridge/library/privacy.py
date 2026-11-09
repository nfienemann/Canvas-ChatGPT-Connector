"""Reviewed library result vocabulary; never learns fields from file content."""

FIELDS = frozenset(
    """
quota committed_bytes reserved_bytes items reserved_items maximum_bytes maximum_items
derived_bytes maximum_derived_bytes limits document_bytes image_bytes chunk_bytes selection_files
extract_document_bytes extract_pptx_bytes device_upload host_file_inputs host_file_picker
transfer_seconds idle_seconds
ingress_requests export_original_bytes
original_download inline_images audio_video upload_url history_versions history_days temporary_import_hours
item_id version_id document_id media_kind mime_type size_bytes original_sha256 storage_state
processing_state source_origin acquisition_channel read_text search_text render_visual download_original
permitted_channels metadata_revision permission_revision representation_id representation_version
omitted_modes search_coverage scanned_items scanned_parts available_parts bounded_omissions
tags collection_id next_cursor correlation_id next_action retryable state mode retention
capabilities policy_version expires_at created_at title coverage warnings schema_version
    delivery_id download_url delivery_channel
    """.split()
)
