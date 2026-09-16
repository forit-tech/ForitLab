"""Pydantic-модели ответов. Нужны не для красоты, а чтобы /docs был читаемым."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["ok", "info", "warn", "alert"]


# ---------------------------------------------------------------------------
# Витрина
# ---------------------------------------------------------------------------


class ToolInfo(BaseModel):
    id: str
    title: str
    summary: str
    status: Literal["available", "planned"]
    base_path: str | None = None
    docs_anchor: str | None = None


class ServiceInfo(BaseModel):
    service: str
    version: str
    description: str
    docs_url: str | None
    openapi_url: str | None
    tools: list[ToolInfo]
    endpoints: dict[str, str]


class HealthResponse(BaseModel):
    ok: bool
    status: Literal["healthy", "degraded"]
    version: str
    reports_store: str
    storage_writable: bool
    problems: list[str] = Field(default_factory=list)
    time: str


class StatusResponse(BaseModel):
    """Диагностика окружения: чтобы видеть, обо что именно спотыкается хостинг."""

    service: str
    version: str
    python: str
    implementation: str
    platform: str
    pid: int
    server: str
    cwd: str
    base_dir: str
    state_dir: str
    state_dir_writable: bool
    reports_store: str
    reports_count: int
    uptime_seconds: float
    process_started_at: str
    dependencies: dict[str, str]
    limits: dict[str, float]


class LimitsResponse(BaseModel):
    max_upload_mb: float
    max_rows: int
    max_columns: int
    max_categories: int
    numeric_sample: int
    reports_store: str
    max_reports: int
    report_ttl_hours: int
    notes: list[str]


# ---------------------------------------------------------------------------
# Отчёт о дрейфе
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    code: str = Field(examples=["distribution.psi"])
    severity: Severity
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ColumnReport(BaseModel):
    column: str
    status: Severity
    analysis: Literal["numeric", "categorical", "datetime", "identifier", "text", "structural"]
    reference_type: str | None
    current_type: str | None
    metrics: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


class TableInfo(BaseModel):
    name: str
    rows: int
    columns: int
    format: str
    encoding: str
    delimiter: str | None = None
    truncated: bool = False
    dropped_columns: list[str] = Field(default_factory=list)


class InputsBlock(BaseModel):
    reference: TableInfo
    current: TableInfo


class RowsBlock(BaseModel):
    reference: int
    current: int
    diff: int
    change: float | None = None


class TypeChange(BaseModel):
    column: str
    from_: str | None = Field(alias="from")
    to: str | None

    model_config = ConfigDict(populate_by_name=True)


class SchemaBlock(BaseModel):
    columns_reference: int
    columns_current: int
    unchanged: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    type_changed: list[TypeChange] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class TopOffender(BaseModel):
    column: str
    status: Severity
    metrics: dict[str, Any] = Field(default_factory=dict)


class SummaryBlock(BaseModel):
    status: Severity
    verdict: str
    columns_analyzed: int
    columns_with_findings: int
    alerts: int
    warnings: int
    notes: int
    significant_changes: int
    top_offenders: list[TopOffender] = Field(default_factory=list)


class Thresholds(BaseModel):
    psi_warn: float
    psi_alert: float
    p_value_alert: float
    missing_warn: float
    missing_alert: float
    numeric_bins: int


class StorageInfo(BaseModel):
    stored: bool
    backend: str
    reason: str | None = None


class DriftReport(BaseModel):
    report_id: str
    tool: str
    engine: str
    created_at: str
    duration_ms: float
    inputs: InputsBlock
    rows: RowsBlock
    schema_block: SchemaBlock = Field(alias="schema")
    columns: list[ColumnReport]
    summary: SummaryBlock
    thresholds: Thresholds
    storage: StorageInfo

    model_config = ConfigDict(populate_by_name=True)


class ReportListItem(BaseModel):
    report_id: str
    created_at: str
    status: Severity
    verdict: str
    reference: str
    current: str
    alerts: int
    warnings: int


class ReportList(BaseModel):
    backend: str
    count: int
    items: list[ReportListItem]


class ProfileResponse(BaseModel):
    name: str
    rows: int
    columns: int
    format: str
    encoding: str
    delimiter: str | None = None
    truncated: bool = False
    dropped_columns: list[str] = Field(default_factory=list)
    column_profiles: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: float


class DeleteResponse(BaseModel):
    deleted: bool
    report_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
