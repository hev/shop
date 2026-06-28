import type * as Models from "./models.js";
export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export interface HevlayerOptions {
    baseUrl?: string | null;
    apiKey?: string | null;
    timeout?: number | null;
    fetch?: FetchLike;
}
export interface RequestOptions {
    withPerf?: boolean;
    signal?: AbortSignal;
}
export interface FetchDocumentOptions extends RequestOptions {
    includeAttributes?: string[];
}
export interface GetCostSnapshotOptions extends RequestOptions {
    window?: Models.CostWindow;
}
export interface GetCostTimeseriesOptions extends RequestOptions {
    window?: Models.CostWindow;
    step?: Models.CostStep;
}
export interface GetScanResultsOptions extends RequestOptions {
    limit?: number;
    offset?: number;
}
export interface HintCacheWarmOptions extends RequestOptions {
    turbopuffer?: boolean;
    documents?: boolean;
    snapshots?: boolean;
    blobs?: boolean;
    blobBudgetBytes?: number;
    pageSize?: number;
}
export interface ListCheckpointsOptions extends RequestOptions {
    limit?: number;
    before?: string;
}
export interface ListClickstreamOptions extends RequestOptions {
    traceId?: string;
    tags?: string[];
    from_?: string;
    to?: string;
    before?: string;
    limit?: number;
}
export interface ListKeysOptions extends RequestOptions {
    includeRevoked?: boolean;
}
export interface ListMetricsCatalogOptions extends RequestOptions {
    family?: Models.MetricFamily;
}
export interface ListNamespaceHistoryOptions extends RequestOptions {
    limit?: number;
    before?: string;
}
export interface ListNamespacesOptions extends RequestOptions {
    prefix?: string;
    cursor?: string;
    pageSize?: number;
}
export interface ListSearchHistoryOptions extends RequestOptions {
    tags?: string[];
    from_?: string;
    to?: string;
    before?: string;
    limit?: number;
}
export interface ListSnapshotActivityOptions extends RequestOptions {
    since?: number;
    limit?: number;
    namespace_?: string;
    cursor?: string;
}
export interface ListTurbopufferNamespacesOptions extends RequestOptions {
    cursor?: string;
    prefix?: string;
    pageSize?: number;
}
export interface PutBlobOptions extends RequestOptions {
    warm?: boolean;
}
export interface QueryMetricsOptions extends RequestOptions {
    query?: string;
    time?: string;
    timeout?: string;
}
export interface QueryMetricsApiV1Options extends RequestOptions {
    query?: string;
    time?: string;
    timeout?: string;
}
export interface QueryMetricsRangeOptions extends RequestOptions {
    query?: string;
    start?: string;
    end?: string;
    step?: string;
    timeout?: string;
}
export interface QueryMetricsRangeApiV1Options extends RequestOptions {
    query?: string;
    start?: string;
    end?: string;
    step?: string;
    timeout?: string;
}
export interface QueryNamespaceOptions extends RequestOptions {
    searchQuery?: string;
    tags?: string[];
}
export interface WarmCacheOptions extends RequestOptions {
    pageSize?: number;
}
export interface LayerPerf {
    latencyMs: number;
    cacheStatus: string | null;
}
export interface LayerResponse<T> {
    data: T;
    perf: LayerPerf;
}
export declare class HevlayerError extends Error {
    readonly statusCode: number;
    readonly kind: string | null;
    readonly body: unknown;
    readonly response: Response;
    constructor(statusCode: number, message: string, options: {
        kind?: string | null;
        body?: unknown;
        response: Response;
    });
}
export declare class Hevlayer {
    private readonly baseUrl;
    private readonly apiKey;
    private readonly timeout;
    private readonly fetchImpl;
    constructor(options?: HevlayerOptions);
    authenticateKey(body: Models.AuthenticateKeyRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.AuthenticateKeyResponse>;
    authenticateKey(body: Models.AuthenticateKeyRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.AuthenticateKeyResponse>>;
    batchQueryNamespace(namespace_: string, body: Models.BatchQueryRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.BatchQueryResponse>;
    batchQueryNamespace(namespace_: string, body: Models.BatchQueryRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.BatchQueryResponse>>;
    branchNamespace(namespace_: string, body: Models.TurbopufferBranchFromRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferWriteResponse>;
    branchNamespace(namespace_: string, body: Models.TurbopufferBranchFromRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferWriteResponse>>;
    claimDocuments(pipelineId: string, body: Models.ClaimDocumentsRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ClaimDocumentsResponse>;
    claimDocuments(pipelineId: string, body: Models.ClaimDocumentsRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ClaimDocumentsResponse>>;
    claimUdfItems(udfId: string, body: Models.UdfClaimRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfClaimResponse>;
    claimUdfItems(udfId: string, body: Models.UdfClaimRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfClaimResponse>>;
    completeUdfItems(udfId: string, body: Models.UdfCompleteRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfItemsResponse>;
    completeUdfItems(udfId: string, body: Models.UdfCompleteRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfItemsResponse>>;
    copyNamespace(namespace_: string, body: Models.TurbopufferCopyFromRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferWriteResponse>;
    copyNamespace(namespace_: string, body: Models.TurbopufferCopyFromRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferWriteResponse>>;
    createCheckpoint(namespace_: string, body: Models.CreateCheckpointRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Checkpoint>;
    createCheckpoint(namespace_: string, body: Models.CreateCheckpointRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Checkpoint>>;
    createPipeline(body: Models.CreatePipelineRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Pipeline>;
    createPipeline(body: Models.CreatePipelineRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Pipeline>>;
    createScan(namespace_: string, body: Models.CreateScanRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ScanCountResponse | Models.ScanJob>;
    createScan(namespace_: string, body: Models.CreateScanRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ScanCountResponse | Models.ScanJob>>;
    createSnapshot(namespace_: string, body: Models.CreateSnapshotRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotJob>;
    createSnapshot(namespace_: string, body: Models.CreateSnapshotRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotJob>>;
    createUdf(body: Models.CreateUdfRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Udf>;
    createUdf(body: Models.CreateUdfRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Udf>>;
    deleteKey(keyId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    deleteKey(keyId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    deleteNamespace(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    deleteNamespace(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    deletePipeline(pipelineId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    deletePipeline(pipelineId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    deleteScan(namespace_: string, scanId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    deleteScan(namespace_: string, scanId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    deleteUdf(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    deleteUdf(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    discoverUdf(udfId: string, body: Models.UdfDiscoverRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfDiscoverResponse>;
    discoverUdf(udfId: string, body: Models.UdfDiscoverRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfDiscoverResponse>>;
    evaluateTurbopufferRecall(namespace_: string, body: Models.TurbopufferRecallRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferRecallResponse>;
    evaluateTurbopufferRecall(namespace_: string, body: Models.TurbopufferRecallRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferRecallResponse>>;
    explainTurbopufferQuery(namespace_: string, body: Models.TurbopufferQueryRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferExplainQueryResponse>;
    explainTurbopufferQuery(namespace_: string, body: Models.TurbopufferQueryRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferExplainQueryResponse>>;
    failUdfItems(udfId: string, body: Models.UdfFailRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfItemsResponse>;
    failUdfItems(udfId: string, body: Models.UdfFailRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfItemsResponse>>;
    fetchDocument(namespace_: string, docId: string, opts?: FetchDocumentOptions & {
        withPerf?: false;
    }): Promise<Models.Document>;
    fetchDocument(namespace_: string, docId: string, opts: FetchDocumentOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Document>>;
    fetchDocuments(namespace_: string, body: Models.FetchDocumentsRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.FetchDocumentsResponse>;
    fetchDocuments(namespace_: string, body: Models.FetchDocumentsRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.FetchDocumentsResponse>>;
    getBlob(namespace_: string, sha256: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Uint8Array>;
    getBlob(namespace_: string, sha256: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Uint8Array>>;
    getCheckpoint(namespace_: string, label: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Checkpoint>;
    getCheckpoint(namespace_: string, label: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Checkpoint>>;
    getCostRateCard(opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.RateCard>;
    getCostRateCard(opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.RateCard>>;
    getCostSnapshot(opts?: GetCostSnapshotOptions & {
        withPerf?: false;
    }): Promise<Models.CostSnapshot>;
    getCostSnapshot(opts: GetCostSnapshotOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.CostSnapshot>>;
    getCostTimeseries(opts?: GetCostTimeseriesOptions & {
        withPerf?: false;
    }): Promise<Models.CostTimeseries>;
    getCostTimeseries(opts: GetCostTimeseriesOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.CostTimeseries>>;
    getKey(keyId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ApiKey>;
    getKey(keyId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ApiKey>>;
    getMetricCatalogEntry(name: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.MetricCatalogEntry>;
    getMetricCatalogEntry(name: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.MetricCatalogEntry>>;
    getNamespaceMetadata(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.NamespaceMetadata>;
    getNamespaceMetadata(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.NamespaceMetadata>>;
    getNamespaceSnapshot(namespace_: string, sha: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotBody>;
    getNamespaceSnapshot(namespace_: string, sha: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotBody>>;
    getPipelineDocumentChunks(pipelineId: string, docId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.GetChunksResponse>;
    getPipelineDocumentChunks(pipelineId: string, docId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.GetChunksResponse>>;
    getPipelineStatus(pipelineId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.PipelineStatus>;
    getPipelineStatus(pipelineId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PipelineStatus>>;
    getScan(namespace_: string, scanId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ScanJob>;
    getScan(namespace_: string, scanId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ScanJob>>;
    getScanResults(namespace_: string, scanId: string, opts?: GetScanResultsOptions & {
        withPerf?: false;
    }): Promise<Models.ScanIdsResponse | Models.ScanValuesResponse>;
    getScanResults(namespace_: string, scanId: string, opts: GetScanResultsOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ScanIdsResponse | Models.ScanValuesResponse>>;
    getSnapshotJob(namespace_: string, jobId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotJob>;
    getSnapshotJob(namespace_: string, jobId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotJob>>;
    getTurbopufferNamespaceSchema(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferSchema>;
    getTurbopufferNamespaceSchema(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferSchema>>;
    getTurbopufferV1NamespaceMetadata(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.NamespaceMetadata>;
    getTurbopufferV1NamespaceMetadata(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.NamespaceMetadata>>;
    getUdf(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.GetUdfResponse>;
    getUdf(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.GetUdfResponse>>;
    getUdfStatus(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfStatus>;
    getUdfStatus(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfStatus>>;
    getVectorstore(name: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.VectorStore>;
    getVectorstore(name: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.VectorStore>>;
    getWarehouse(name: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Warehouse>;
    getWarehouse(name: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Warehouse>>;
    getWarmJob(namespace_: string, jobId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.WarmJob>;
    getWarmJob(namespace_: string, jobId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.WarmJob>>;
    heartbeatDocuments(pipelineId: string, body: Models.HeartbeatDocumentsRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.DocumentsStageResponse>;
    heartbeatDocuments(pipelineId: string, body: Models.HeartbeatDocumentsRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.DocumentsStageResponse>>;
    heartbeatUdfItems(udfId: string, body: Models.UdfHeartbeatRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfItemsResponse>;
    heartbeatUdfItems(udfId: string, body: Models.UdfHeartbeatRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfItemsResponse>>;
    hintCacheWarm(namespace_: string, opts?: HintCacheWarmOptions & {
        withPerf?: false;
    }): Promise<Models.HintCacheWarmResponse>;
    hintCacheWarm(namespace_: string, opts: HintCacheWarmOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.HintCacheWarmResponse>>;
    importNamespace(namespace_: string, body: Uint8Array | ArrayBuffer | Blob, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Record<string, unknown>>;
    importNamespace(namespace_: string, body: Uint8Array | ArrayBuffer | Blob, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Record<string, unknown>>>;
    listCheckpoints(namespace_: string, opts?: ListCheckpointsOptions & {
        withPerf?: false;
    }): Promise<Models.CheckpointList>;
    listCheckpoints(namespace_: string, opts: ListCheckpointsOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.CheckpointList>>;
    listClickstream(namespace_: string, opts?: ListClickstreamOptions & {
        withPerf?: false;
    }): Promise<Models.ClickstreamListResponse>;
    listClickstream(namespace_: string, opts: ListClickstreamOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ClickstreamListResponse>>;
    listKeys(opts?: ListKeysOptions & {
        withPerf?: false;
    }): Promise<Models.ApiKeyList>;
    listKeys(opts: ListKeysOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ApiKeyList>>;
    listMetricsCatalog(opts?: ListMetricsCatalogOptions & {
        withPerf?: false;
    }): Promise<Models.MetricCatalog>;
    listMetricsCatalog(opts: ListMetricsCatalogOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.MetricCatalog>>;
    listNamespaceHistory(namespace_: string, opts?: ListNamespaceHistoryOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotHistoryEntry[]>;
    listNamespaceHistory(namespace_: string, opts: ListNamespaceHistoryOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotHistoryEntry[]>>;
    listNamespaces(opts?: ListNamespacesOptions & {
        withPerf?: false;
    }): Promise<Models.NamespaceList>;
    listNamespaces(opts: ListNamespacesOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.NamespaceList>>;
    listPipelines(opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.PipelineList>;
    listPipelines(opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PipelineList>>;
    listScans(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ScanJobList>;
    listScans(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ScanJobList>>;
    listSearchHistory(namespace_: string, opts?: ListSearchHistoryOptions & {
        withPerf?: false;
    }): Promise<Models.SearchHistoryListResponse>;
    listSearchHistory(namespace_: string, opts: ListSearchHistoryOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SearchHistoryListResponse>>;
    listSnapshotActivity(opts?: ListSnapshotActivityOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotActivityList>;
    listSnapshotActivity(opts: ListSnapshotActivityOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotActivityList>>;
    listSnapshotJobs(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.SnapshotJobList>;
    listSnapshotJobs(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.SnapshotJobList>>;
    listTurbopufferNamespaces(opts?: ListTurbopufferNamespacesOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferNamespaceList>;
    listTurbopufferNamespaces(opts: ListTurbopufferNamespacesOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferNamespaceList>>;
    listUdfs(opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfList>;
    listUdfs(opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfList>>;
    listVectorstores(opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.VectorStoreList>;
    listVectorstores(opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.VectorStoreList>>;
    listWarehouses(opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.WarehouseList>;
    listWarehouses(opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.WarehouseList>>;
    listWarmJobs(namespace_: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.WarmJobList>;
    listWarmJobs(namespace_: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.WarmJobList>>;
    mintKey(body: Models.MintKeyRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.MintKeyResponse>;
    mintKey(body: Models.MintKeyRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.MintKeyResponse>>;
    pauseUdf(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Udf>;
    pauseUdf(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Udf>>;
    putBlob(namespace_: string, body: Uint8Array | ArrayBuffer | Blob, opts?: PutBlobOptions & {
        withPerf?: false;
    }): Promise<Models.BlobPutResponse>;
    putBlob(namespace_: string, body: Uint8Array | ArrayBuffer | Blob, opts: PutBlobOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.BlobPutResponse>>;
    putPipelineDocumentChunks(pipelineId: string, docId: string, body: Models.PutChunksRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StageDocumentResponse>;
    putPipelineDocumentChunks(pipelineId: string, docId: string, body: Models.PutChunksRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StageDocumentResponse>>;
    putPipelineDocumentVectors(pipelineId: string, docId: string, body: Models.PutVectorsRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    putPipelineDocumentVectors(pipelineId: string, docId: string, body: Models.PutVectorsRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    query(body: Models.FederatedQueryRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.FederatedQueryResponse>;
    query(body: Models.FederatedQueryRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.FederatedQueryResponse>>;
    queryAgent(name: string, body: Models.AgentQueryRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.AgentQueryResponse>;
    queryAgent(name: string, body: Models.AgentQueryRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.AgentQueryResponse>>;
    queryMetrics(opts?: QueryMetricsOptions & {
        withPerf?: false;
    }): Promise<Models.PrometheusResponse>;
    queryMetrics(opts: QueryMetricsOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PrometheusResponse>>;
    queryMetricsApiV1(opts?: QueryMetricsApiV1Options & {
        withPerf?: false;
    }): Promise<Models.PrometheusResponse>;
    queryMetricsApiV1(opts: QueryMetricsApiV1Options & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PrometheusResponse>>;
    queryMetricsRange(opts?: QueryMetricsRangeOptions & {
        withPerf?: false;
    }): Promise<Models.PrometheusResponse>;
    queryMetricsRange(opts: QueryMetricsRangeOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PrometheusResponse>>;
    queryMetricsRangeApiV1(opts?: QueryMetricsRangeApiV1Options & {
        withPerf?: false;
    }): Promise<Models.PrometheusResponse>;
    queryMetricsRangeApiV1(opts: QueryMetricsRangeApiV1Options & {
        withPerf: true;
    }): Promise<LayerResponse<Models.PrometheusResponse>>;
    queryNamespace(namespace_: string, body: Models.QueryRequest | Record<string, unknown>, opts?: QueryNamespaceOptions & {
        withPerf?: false;
    }): Promise<Models.QueryResponse>;
    queryNamespace(namespace_: string, body: Models.QueryRequest | Record<string, unknown>, opts: QueryNamespaceOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.QueryResponse>>;
    queryTurbopufferNamespace(namespace_: string, body: Models.TurbopufferQueryRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferQueryResponse>;
    queryTurbopufferNamespace(namespace_: string, body: Models.TurbopufferQueryRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferQueryResponse>>;
    resetFailedUdf(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.UdfItemsResponse>;
    resetFailedUdf(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.UdfItemsResponse>>;
    resumeUdf(udfId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.Udf>;
    resumeUdf(udfId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.Udf>>;
    revokeKey(keyId: string, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.ApiKey>;
    revokeKey(keyId: string, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.ApiKey>>;
    setDocumentsStage(pipelineId: string, body: Models.SetDocumentsStageRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.DocumentsStageResponse>;
    setDocumentsStage(pipelineId: string, body: Models.SetDocumentsStageRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.DocumentsStageResponse>>;
    updateTurbopufferNamespaceMetadata(namespace_: string, body: Models.TurbopufferMetadataPatch | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.NamespaceMetadata>;
    updateTurbopufferNamespaceMetadata(namespace_: string, body: Models.TurbopufferMetadataPatch | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.NamespaceMetadata>>;
    updateTurbopufferNamespaceSchema(namespace_: string, body: Models.TurbopufferSchema | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferSchema>;
    updateTurbopufferNamespaceSchema(namespace_: string, body: Models.TurbopufferSchema | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferSchema>>;
    warmCache(namespace_: string, opts?: WarmCacheOptions & {
        withPerf?: false;
    }): Promise<Models.WarmJob>;
    warmCache(namespace_: string, opts: WarmCacheOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.WarmJob>>;
    writeNamespace(namespace_: string, body: Models.TurbopufferWriteRequest | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferWriteResponse>;
    writeNamespace(namespace_: string, body: Models.TurbopufferWriteRequest | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferWriteResponse>>;
    ensurePipeline(body: Models.CreatePipelineRequest | Record<string, unknown>): Promise<Models.Pipeline>;
    releaseDocuments(pipelineId: string, documentIds: string[], opts?: DocumentStageOptions & {
        withPerf?: false;
    }): Promise<Models.DocumentsStageResponse>;
    releaseDocuments(pipelineId: string, documentIds: string[], opts: DocumentStageOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.DocumentsStageResponse>>;
    failDocuments(pipelineId: string, documentIds: string[], opts?: DocumentStageOptions & {
        withPerf?: false;
    }): Promise<Models.DocumentsStageResponse>;
    failDocuments(pipelineId: string, documentIds: string[], opts: DocumentStageOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.DocumentsStageResponse>>;
    completeDocuments(pipelineId: string, documentIds: string[], opts?: DocumentStageOptions & {
        withPerf?: false;
    }): Promise<Models.DocumentsStageResponse>;
    completeDocuments(pipelineId: string, documentIds: string[], opts: DocumentStageOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.DocumentsStageResponse>>;
    writeSingleVector(pipelineId: string, docId: string, vector: Models.VectorEntry | Record<string, unknown>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.StatusResponse>;
    writeSingleVector(pipelineId: string, docId: string, vector: Models.VectorEntry | Record<string, unknown>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.StatusResponse>>;
    waitForScan(namespace: string, scanId: string, opts?: ScanWaitOptions): Promise<Models.ScanJob>;
    scan(namespace: string, body: Models.CreateScanRequest | Record<string, unknown>, opts?: ScanOptions): Promise<Models.ScanJob>;
    warmNamespace(namespace: string, opts?: WarmCacheOptions & {
        withPerf?: false;
    }): Promise<Models.WarmJob>;
    warmNamespace(namespace: string, opts: WarmCacheOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.WarmJob>>;
    patchColumns(namespace: string, ids: string[], attrs: Record<string, unknown[]>, opts?: RequestOptions & {
        withPerf?: false;
    }): Promise<Models.TurbopufferWriteResponse>;
    patchColumns(namespace: string, ids: string[], attrs: Record<string, unknown[]>, opts: RequestOptions & {
        withPerf: true;
    }): Promise<LayerResponse<Models.TurbopufferWriteResponse>>;
    private setDocumentsStageHelper;
    private requestJson;
    private applyLayerHeaders;
    private requestBytes;
    private fetchJson;
    private requestSignal;
    private urlFor;
    private queryParamValue;
    private searchHistoryHeaders;
    private decodeJsonResponse;
    private errorFromResponse;
}
export interface DocumentStageOptions extends RequestOptions {
    fromStage?: string;
    workerId?: string;
}
export interface ScanWaitOptions {
    initialDelayMs?: number;
    maxDelayMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
}
export interface ScanOptions extends ScanWaitOptions {
}
