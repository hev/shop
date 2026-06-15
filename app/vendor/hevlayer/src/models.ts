export type JSONValue = null | boolean | number | string | JSONValue[] | { [key: string]: JSONValue };
export type TurbopufferFilter =
  | [string, string, JSONValue]
  | ["And" | "Or", TurbopufferFilter[]]
  | ["Not", TurbopufferFilter]
  | JSONValue[]
  | Record<string, JSONValue>;
export type TurbopufferRankBy =
  | [string, "ANN", number[]]
  | [string, "BM25", string]
  | [string, string, JSONValue]
  | JSONValue[]
  | Record<string, JSONValue>;

export interface CreatePipelineRequest {
  [key: string]: unknown;
  id: string;
  target_namespace: string;
  distance_metric?: string;
}

export interface Pipeline {
  [key: string]: unknown;
  id: string;
  target_namespace: string;
  distance_metric: string;
  created_at: string;
}

export interface PipelineList {
  [key: string]: unknown;
  pipelines: Pipeline[];
}

export interface PipelineStatus {
  [key: string]: unknown;
  pipeline_id: string;
  counts: Record<string, number>;
  pending_count: number;
  processing_count: number;
  failed_count: number;
  indexed_rate_per_min: number;
  rate_window_seconds: number;
}

export interface ClaimDocumentsRequest {
  [key: string]: unknown;
  stage?: string;
  claim_stage?: string;
  limit?: number;
  worker_id: string;
  lease_seconds?: number;
  document_id_prefix?: string | null;
}

export interface ClaimDocumentsResponse {
  [key: string]: unknown;
  pipeline_id: string;
  stage: string;
  claim_stage: string;
  worker_id: string;
  documents: string[];
}

export interface HeartbeatDocumentsRequest {
  [key: string]: unknown;
  document_ids: string[];
  stage?: string;
  worker_id: string;
}

export interface SetDocumentsStageRequest {
  [key: string]: unknown;
  document_ids: string[];
  stage: string;
  from_stage?: string | null;
  worker_id?: string | null;
  create_missing?: boolean;
}

export interface DocumentsStageResponse {
  [key: string]: unknown;
  pipeline_id: string;
  stage: string;
  updated: number;
}

export interface StageDocumentResponse {
  [key: string]: unknown;
  pipeline_id: string;
  document_id: string;
  stage: string;
  chunk_count: number;
  chunk_ids: string[];
}

export interface Chunk {
  [key: string]: unknown;
  id: string;
  text?: string;
  metadata?: Record<string, unknown>;
}

export interface PutChunksRequest {
  [key: string]: unknown;
  chunks: Chunk[];
}

export type GetChunksResponse = Chunk[];

export interface VectorEntry {
  [key: string]: unknown;
  id: string;
  vector: number[];
  attributes?: Record<string, unknown>;
}

export interface PutVectorsRequest {
  [key: string]: unknown;
  vectors: VectorEntry[];
}

export interface CreateUdfRequest {
  [key: string]: unknown;
  id: string;
  spec: UdfSpec;
}

export interface Udf {
  [key: string]: unknown;
  id: string;
  spec: UdfSpec;
  paused: boolean;
  created_at: string;
  updated_at: string;
}

export interface UdfList {
  [key: string]: unknown;
  udfs: Udf[];
}

export interface GetUdfResponse {
  [key: string]: unknown;
  udf: Udf;
  status: UdfStatus;
}

export interface UdfStatus {
  [key: string]: unknown;
  udf_id: string;
  paused: boolean;
  active_namespaces: string[];
  discovery: UdfDiscoveryStatus;
  counts: Record<string, number>;
  pending_count: number;
  processing_count: number;
  failed_count: number;
  indexed_rate_per_min: number;
  rate_window_seconds: number;
}

export interface UdfDiscoveryStatus {
  [key: string]: unknown;
  sweeps_completed: number;
  last_completed_at: string | null;
}

export interface UdfSpec {
  [key: string]: unknown;
  index_selector?: unknown;
  target_namespaces?: string[];
  inputs?: string[];
  version?: string;
  filter?: TurbopufferFilter;
  worker: UdfWorkerSpec;
  schedule?: UdfScheduleSpec;
  retry?: UdfRetrySpec;
  triggers?: UdfTrigger[];
  invalidates?: string[];
}

export type UdfTrigger = "discovery" | "write";

export interface UdfWorkerSpec {
  [key: string]: unknown;
  image?: string | null;
  url?: string | null;
  port?: number | null;
  batch_size?: number;
  timeout_seconds?: number;
  pod_spec?: unknown;
}

export interface UdfScheduleSpec {
  [key: string]: unknown;
  discovery_interval_seconds?: number;
  lease_seconds?: number;
  max_in_flight_batches?: number;
  max_concurrent_scans?: number;
}

export interface UdfRetrySpec {
  [key: string]: unknown;
  max_attempts?: number;
  initial_backoff_seconds?: number;
  max_backoff_seconds?: number;
}

export interface UdfDiscoverRequest {
  [key: string]: unknown;
  namespaces?: string[];
  page_size?: number;
}

export interface UdfDiscoverResponse {
  [key: string]: unknown;
  udf_id: string;
  enqueued: number;
  namespaces: string[];
}

export interface UdfClaimRequest {
  [key: string]: unknown;
  worker_id: string;
  limit?: number;
  lease_seconds?: number;
}

export interface UdfClaimedItem {
  [key: string]: unknown;
  "namespace": string;
  id: string;
  input: Record<string, unknown>;
}

export interface UdfClaimResponse {
  [key: string]: unknown;
  udf_id: string;
  worker_id: string;
  items: UdfClaimedItem[];
}

export interface UdfItemRef {
  [key: string]: unknown;
  "namespace": string;
  id: string;
}

export interface UdfHeartbeatRequest {
  [key: string]: unknown;
  worker_id: string;
  items: UdfItemRef[];
}

export interface UdfCompleteRequest {
  [key: string]: unknown;
  worker_id: string;
  items: UdfCompleteItem[];
}

export interface UdfCompleteItem {
  [key: string]: unknown;
  "namespace": string;
  id: string;
  attributes?: Record<string, unknown>;
}

export type UdfErrorKind = "transient" | "permanent";

export interface UdfFailRequest {
  [key: string]: unknown;
  worker_id: string;
  items: UdfFailItem[];
}

export interface UdfFailItem {
  [key: string]: unknown;
  "namespace": string;
  id: string;
  kind: UdfErrorKind;
  message?: string | null;
}

export interface UdfItemsResponse {
  [key: string]: unknown;
  udf_id: string;
  updated: number;
}

export interface Document {
  [key: string]: unknown;
  id: string;
  attributes: Record<string, unknown>;
}

export interface FetchDocumentsRequest {
  [key: string]: unknown;
  ids: string[];
  include_attributes?: string[];
}

export interface FetchDocumentsResponse {
  [key: string]: unknown;
  documents: Document[];
  missing: string[];
}

export interface StatusResponse {
  [key: string]: unknown;
  status: string;
  message?: string;
  rows_affected?: number;
  rows_upserted?: number;
  rows_patched?: number;
  rows_deleted?: number;
  billing?: Record<string, unknown>;
}

export interface TurbopufferNamespaceSummary {
  [key: string]: unknown;
  id: string;
}

export interface TurbopufferNamespaceList {
  [key: string]: unknown;
  namespaces: TurbopufferNamespaceSummary[];
  next_cursor?: string;
}

export type TurbopufferSchema = Record<string, unknown>;

export interface TurbopufferMetadataPatch {
  [key: string]: unknown;
  pinning?: unknown;
}

export type TurbopufferWriteRequest = Record<string, unknown>;

export interface TurbopufferBranchFromRequest {
  [key: string]: unknown;
  branch_from_namespace: Record<string, unknown>;
}

export interface TurbopufferCopyFromRequest {
  [key: string]: unknown;
  copy_from_namespace: string | Record<string, unknown>;
}

export interface TurbopufferWriteResponse {
  [key: string]: unknown;
  status: string;
  message: string;
  rows_affected: number;
  rows_upserted?: number;
  rows_patched?: number;
  rows_deleted?: number;
  rows_remaining?: boolean;
  upserted_ids?: unknown[];
  patched_ids?: unknown[];
  deleted_ids?: unknown[];
  billing: Record<string, unknown>;
  performance?: Record<string, unknown>;
}

export interface TurbopufferQueryRequest {
  [key: string]: unknown;
  filters?: TurbopufferFilter;
  rank_by?: TurbopufferRankBy;
}

export interface TurbopufferQueryResponse {
  [key: string]: unknown;
  rows?: Record<string, unknown>[];
  aggregations?: Record<string, unknown>;
  aggregation_groups?: Record<string, unknown>[];
  billing?: Record<string, unknown>;
  performance?: Record<string, unknown>;
}

export interface TurbopufferMultiQueryRequest {
  [key: string]: unknown;
  queries: TurbopufferQueryRequest[];
  consistency?: Record<string, unknown>;
  vector_encoding?: string;
}

export interface TurbopufferMultiQueryResponse {
  [key: string]: unknown;
  results: TurbopufferQueryResponse[];
  billing?: Record<string, unknown>;
  performance?: Record<string, unknown>;
  stable_as_of?: number | null;
}

export interface TurbopufferExplainQueryResponse {
  [key: string]: unknown;
  plan_text?: string;
}

export interface TurbopufferRecallRequest {
  [key: string]: unknown;
  num?: number;
  top_k?: number;
  filters?: TurbopufferFilter;
  rank_by?: TurbopufferRankBy;
  include_ground_truth?: boolean;
}

export interface TurbopufferRecallResponse {
  [key: string]: unknown;
  avg_recall: number;
  avg_exhaustive_count: number;
  avg_ann_count: number;
  ground_truth?: Record<string, unknown>[];
}

export interface HintCacheWarmResponse {
  [key: string]: unknown;
  "namespace"?: string;
  turbopuffer?: WarmStepResponse;
  documents?: WarmDocumentsResponse;
  snapshots?: WarmSnapshotsResponse;
}

export type JobStatus = "running" | "completed" | "failed";

export type SnapshotSource = "auto" | "stored" | "cache" | "origin";

export type ScanSource = "auto" | "cache" | "origin" | "snapshot";

export type ScanCountSource = "auto" | "snapshot" | "cache" | "origin";

export type ScanMode = "ids" | "count" | "values";

export type ScanCountServedBy = "snapshot" | "cache" | "origin";

export interface CreateSnapshotRequest {
  [key: string]: unknown;
  field: string;
  source?: SnapshotSource;
  filters?: TurbopufferFilter;
  page_size?: number;
}

export interface CreateScanRequest {
  [key: string]: unknown;
  source?: ScanCountSource;
  filters?: TurbopufferFilter;
  fts?: FtsScan;
  ann?: AnnScan;
  mode?: ScanMode;
  field?: string;
  exhaustive?: boolean;
  threads?: number;
  page_size?: number;
  timeout_seconds?: number;
}

export interface FtsScan {
  [key: string]: unknown;
  field: string;
  query: string;
}

export interface AnnScan {
  [key: string]: unknown;
  vector: number[];
  field?: string;
  radius: number;
}

export type WarmStepStatus = "skipped" | "completed" | "started" | "no_snapshot";

export interface WarmStepResponse {
  [key: string]: unknown;
  enabled: boolean;
  status: WarmStepStatus;
}

export interface WarmDocumentsResponse {
  [key: string]: unknown;
  enabled: boolean;
  status: WarmStepStatus;
  job?: WarmJob;
}

export interface WarmSnapshotsResponse {
  [key: string]: unknown;
  enabled: boolean;
  status: WarmStepStatus;
  key?: string;
  watermark_ms?: number;
  sha?: string;
}

export interface WarmCacheResponse {
  [key: string]: unknown;
  "namespace": string;
  turbopuffer: WarmStepResponse;
  documents: WarmDocumentsResponse;
  snapshots: WarmSnapshotsResponse;
}

export interface JobBase {
  [key: string]: unknown;
  id: string;
  "namespace": string;
  status: JobStatus;
  progress: number;
  documents_scanned: number;
  stable_as_of?: number;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
}

export interface SnapshotJob {
  [key: string]: unknown;
  id: string;
  "namespace": string;
  status: JobStatus;
  progress: number;
  documents_scanned: number;
  stable_as_of?: number;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
  field: string;
  source: SnapshotSource;
  effective_source?: SnapshotSource;
  sha?: string | null;
}

export interface SnapshotJobList {
  [key: string]: unknown;
  snapshot_jobs: SnapshotJob[];
}

export interface WarmJob {
  [key: string]: unknown;
  id: string;
  "namespace": string;
  status: JobStatus;
  progress: number;
  documents_scanned: number;
  stable_as_of?: number;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
}

export interface WarmJobList {
  [key: string]: unknown;
  warm_jobs: WarmJob[];
}

export interface ScanJob {
  [key: string]: unknown;
  id: string;
  "namespace": string;
  status: JobStatus;
  progress: number;
  documents_scanned: number;
  stable_as_of?: number;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
  mode: ScanMode;
  field?: string;
  source: ScanSource;
  effective_source?: ScanSource;
  unique_values?: number;
  truncated?: boolean;
  bounded?: boolean;
  approximate?: boolean;
  snapshot_sha?: string;
  watermark_ms?: number;
  threads?: number;
}

export interface ScanJobList {
  [key: string]: unknown;
  scans: ScanJob[];
}

export interface ScanValue {
  [key: string]: unknown;
  v: string;
  n: number;
}

export interface ScanValuesResponse {
  [key: string]: unknown;
  values: ScanValue[];
  total: number;
  truncated: boolean;
}

export interface ScanIdsResponse {
  [key: string]: unknown;
  ids: string[];
  total: number;
}

export interface ScanCountResponse {
  [key: string]: unknown;
  count: number;
  served_by: ScanCountServedBy;
  snapshot_sha?: string;
  watermark_ms?: number;
  bounded?: boolean;
  timed_out?: boolean;
  shards_saturated?: number;
  shards_total?: number;
  approximate?: boolean;
  threads?: number;
  elapsed_ms: number;
}

export interface NamespaceList {
  [key: string]: unknown;
  namespaces: NamespaceListEntry[];
  next_cursor?: string | null;
}

export interface NamespaceListEntry {
  [key: string]: unknown;
  name: string;
  row_count?: number | null;
  size_bytes?: number | null;
  stable_as_of_ms?: number | null;
  is_stable?: boolean | null;
  schema_summary?: NamespaceSchemaSummary;
  index?: IndexState;
  cache_state?: NamespaceCacheState;
  last_write_ms?: number | null;
  shadow?: boolean;
  labels?: Record<string, string>;
  metadata_error?: string;
}

export interface NamespaceSchemaSummary {
  [key: string]: unknown;
  vector_dim?: number | null;
  fields?: string[];
}

export interface IndexState {
  [key: string]: unknown;
  status?: "updating" | "up-to-date";
  unindexed_bytes?: number | null;
}

export interface NamespaceCacheState {
  [key: string]: unknown;
  state: "cold" | "warming" | "warm";
  warmed_through_ms?: number | null;
  warm_inflight: boolean;
}

export interface NamespaceMetadata {
  [key: string]: unknown;
  id: string;
  schema: Record<string, unknown>;
  approx_logical_bytes: number;
  approx_row_count: number;
  created_at: string;
  last_write_at?: string | null;
  updated_at: string;
  config?: Record<string, unknown>;
  index?: IndexState;
  layer?: NamespaceMetadataLayer;
}

export interface NamespaceMetadataLayer {
  [key: string]: unknown;
  stable_as_of?: number | null;
  is_stable?: boolean;
  indexed?: boolean | null;
  index_lag_rows?: number | null;
}

export interface QueryRequest {
  [key: string]: unknown;
  vector?: number[];
  nearest_to_id?: string[];
  top_k?: number;
  filters?: TurbopufferFilter;
  include_attributes?: boolean | string[];
  cursor?: string;
  rank_by?: TurbopufferRankBy;
}

export interface HybridEcho {
  [key: string]: unknown;
  tokens: string[];
  tokens_dropped: number;
  fuzziness: "auto" | 0 | 1 | 2;
  rank_constant: number;
  legs: number;
  per_leg_limit: number;
  threads?: number;
}

export interface RoutingEcho {
  [key: string]: unknown;
  route: "hybrid_text" | "semantic" | "fused";
  policy: string;
  tokens: number;
  executed: boolean;
}

export interface QueryResponse {
  [key: string]: unknown;
  rows: Record<string, unknown>[];
  aggregations?: Record<string, unknown>;
  aggregation_groups?: Record<string, unknown>[];
  billing?: Record<string, unknown>;
  performance?: Record<string, unknown>;
  stable_as_of?: number | null;
  next_cursor?: string;
  hybrid?: HybridEcho;
  routing?: RoutingEcho;
}

export interface Error {
  [key: string]: unknown;
  error: string;
  message: string;
}

export interface SnapshotHistoryEntry {
  [key: string]: unknown;
  watermark_ms: number;
  sha: string;
}

export interface SnapshotBody {
  [key: string]: unknown;
  "namespace": string;
  watermark_ms: number;
  sha: string;
  row_count?: number;
  fields: SnapshotField[];
  fields_skipped: SnapshotFieldSkipped[];
}

export interface SnapshotField {
  [key: string]: unknown;
  name: string;
  values: SnapshotValueCount[];
}

export type SnapshotSkipReason = "exceeded_cap";

export interface SnapshotFieldSkipped {
  [key: string]: unknown;
  name: string;
  reason: SnapshotSkipReason;
  distinct_observed: number;
  cap: number;
}

export interface SnapshotValueCount {
  [key: string]: unknown;
  v: string;
  n: number;
}

export interface SnapshotActivityEvent {
  [key: string]: unknown;
  ts_ms: number;
  "namespace": string;
  sha: string;
}

export interface SnapshotActivityList {
  [key: string]: unknown;
  events: SnapshotActivityEvent[];
  next_cursor?: string;
  truncated?: boolean;
}

export type MetricKind = "counter" | "gauge" | "histogram";

export type MetricFamily = "query" | "upsert" | "fetch" | "cache" | "pipeline" | "storage" | "saturation";

export interface MetricAlert {
  [key: string]: unknown;
  summary: string;
  expr: string;
  "for": string;
}

export interface MetricCatalogEntry {
  [key: string]: unknown;
  name: string;
  kind: MetricKind;
  family: MetricFamily;
  labels: string[];
  description: string;
  example_promql: string;
  alert?: MetricAlert;
}

export interface MetricCatalog {
  [key: string]: unknown;
  version: string;
  entries: MetricCatalogEntry[];
}

export type PrometheusResponse = Record<string, unknown>;

export interface SearchHistoryEntry {
  [key: string]: unknown;
  timestamp: string;
  timestamp_nanos: number;
  "namespace": string;
  trace_id?: string;
  raw_query?: string;
  stable_as_of?: number;
  query: Record<string, unknown>;
  top_result_ids: string[];
  tags: string[];
}

export interface SearchHistoryListResponse {
  [key: string]: unknown;
  entries: SearchHistoryEntry[];
  next_cursor?: string;
}

export interface ClickstreamEvent {
  [key: string]: unknown;
  timestamp: string;
  timestamp_nanos: number;
  trace_id: string;
  "namespace": string;
  doc_id: string;
  tags: string[];
  source: string;
  served_from: string;
}

export interface ClickstreamListResponse {
  [key: string]: unknown;
  events: ClickstreamEvent[];
  next_cursor?: string;
}

export interface ApiKeyEntitlement {
  [key: string]: unknown;
  scopes?: ("read" | "write" | "admin")[];
  namespaces?: string[];
  claims?: string[];
}

export type ApiKeyEntitlements = Record<string, ApiKeyEntitlement>;

export type ApiKeyPhase = "Pending" | "Active" | "Revoked" | "Expired";

export interface ApiKey {
  [key: string]: unknown;
  keyId: string;
  name: string;
  owner?: string;
  description?: string;
  entitlements: ApiKeyEntitlements;
  expiresAfter?: string;
  phase: ApiKeyPhase;
  createdAt: string;
  expiresAt?: string;
  revokedAt?: string;
  lastSeenAt?: string;
  lookupHash?: string;
  secretRef?: Record<string, unknown>;
}

export interface ApiKeyList {
  [key: string]: unknown;
  keys: ApiKey[];
}

export interface MintKeyRequest {
  [key: string]: unknown;
  name: string;
  owner?: string;
  description?: string;
  entitlements?: ApiKeyEntitlements;
  expiresAfter?: string;
}

export interface MintKeyResponse {
  [key: string]: unknown;
  keyId: string;
  name: string;
  owner?: string;
  description?: string;
  entitlements: ApiKeyEntitlements;
  expiresAfter?: string;
  phase: ApiKeyPhase;
  createdAt: string;
  expiresAt?: string;
  token: string;
}

export interface AuthenticateKeyRequest {
  [key: string]: unknown;
  token: string;
}

export interface AuthenticateKeyResponse {
  [key: string]: unknown;
  keyId: string;
  name: string;
  owner?: string;
  entitlements: ApiKeyEntitlements;
  expiresAt?: string;
}
