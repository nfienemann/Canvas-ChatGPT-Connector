"""Retention budgets shared by reads, cleanup, workers and restore validation."""

from datetime import timedelta

CONNECTION_LIFETIME = timedelta(days=90)
ANALYSIS_LIFETIME = timedelta(days=30)
RAW_FILE_LIFETIME = timedelta(hours=24)
RAW_PAGE_LIFETIME = timedelta(hours=1)
JOB_LIFETIME = timedelta(days=1)
DIAGNOSTIC_LIFETIME = timedelta(days=7)
BACKUP_LIFETIME = timedelta(days=30)
FENCE_LIFETIME = BACKUP_LIFETIME + timedelta(days=1)
ORPHAN_SECONDS = 600
DERIVATIVE_SECONDS = 600
DOWNLOAD_DEFAULT_SECONDS = 300
DOWNLOAD_MAX_SECONDS = 900
