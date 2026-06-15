class FetchTransportError {
    cause;
    constructor(cause) {
        this.cause = cause;
    }
}
const DEFAULT_BASE_URL = "https://aws-us-east-1.hevlayer.com";
const DEFAULT_TURBOPUFFER_BASE_URL = "https://aws-us-east-1.turbopuffer.com";
const SEARCH_HISTORY_MAX_TAGS = 32;
const SEARCH_HISTORY_MAX_TAG_LENGTH = 128;
const SEARCH_HISTORY_TAG_RE = /^[A-Za-z0-9:_\-.=/+]+$/;
export class HevlayerError extends Error {
    statusCode;
    kind;
    body;
    response;
    constructor(statusCode, message, options) {
        super(message);
        this.name = "HevlayerError";
        this.statusCode = statusCode;
        this.kind = options.kind ?? null;
        this.body = options.body;
        this.response = options.response;
    }
}
export class Hevlayer {
    baseUrl;
    apiKey;
    turbopufferApiKey;
    turbopufferBaseUrl;
    fallbackToTurbopuffer;
    timeout;
    fetchImpl;
    constructor(options = {}) {
        this.baseUrl = cleanBaseUrl(options.baseUrl ?? DEFAULT_BASE_URL, DEFAULT_BASE_URL);
        this.apiKey = cleanToken(options.apiKey);
        this.turbopufferApiKey = cleanToken(options.turbopufferApiKey ?? env("TURBOPUFFER_API_KEY"));
        this.turbopufferBaseUrl = cleanBaseUrl(options.turbopufferBaseUrl ?? env("TURBOPUFFER_API_URL") ?? DEFAULT_TURBOPUFFER_BASE_URL, DEFAULT_TURBOPUFFER_BASE_URL);
        this.fallbackToTurbopuffer = options.fallbackToTurbopuffer ?? true;
        this.timeout = options.timeout === undefined ? 30000 : options.timeout;
        this.fetchImpl = options.fetch ?? defaultFetch();
    }
    async authenticateKey(body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/keys/authenticate",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async branchNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)),
            params: [
                { key: "stainless_overload", value: "branchFrom" }
            ],
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async claimDocuments(pipelineId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/claim",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async claimUdfItems(udfId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/claim",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async completeUdfItems(udfId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/items/complete",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async copyNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)),
            params: [
                { key: "stainless_overload", value: "copyFrom" }
            ],
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async createPipeline(body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/pipelines",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async createScan(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/scans",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async createSnapshot(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/snapshots",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async createUdf(body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async deleteKey(keyId, opts = {}) {
        return this.requestJson({
            method: "DELETE",
            path: "/v2/keys/" + encodeURIComponent(String(keyId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async deleteNamespace(namespace_, opts = {}) {
        return this.requestJson({
            method: "DELETE",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async deletePipeline(pipelineId, opts = {}) {
        return this.requestJson({
            method: "DELETE",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async deleteScan(namespace_, scanId, opts = {}) {
        return this.requestJson({
            method: "DELETE",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/scans/" + encodeURIComponent(String(scanId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async deleteUdf(udfId, opts = {}) {
        return this.requestJson({
            method: "DELETE",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async discoverUdf(udfId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/discover",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async evaluateTurbopufferRecall(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/_debug/recall",
            params: undefined,
            body: body,
            fallback: { method: "POST", path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/_debug/recall" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async explainTurbopufferQuery(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/explain_query",
            params: undefined,
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/explain_query" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async failUdfItems(udfId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/items/fail",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async fetchDocument(namespace_, docId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/documents/" + encodeURIComponent(String(docId)),
            params: [
                { key: "include_attributes", value: opts.includeAttributes }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async fetchDocuments(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/documents",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getKey(keyId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/keys/" + encodeURIComponent(String(keyId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getMetricCatalogEntry(name, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/catalog/" + encodeURIComponent(String(name)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getNamespaceMetadata(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/metadata",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getNamespaceSnapshot(namespace_, sha, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/snapshots/" + encodeURIComponent(String(sha)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getPipelineDocumentChunks(pipelineId, docId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/documents/" + encodeURIComponent(String(docId)) + "/chunks",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getPipelineStatus(pipelineId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/status",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getScan(namespace_, scanId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/scans/" + encodeURIComponent(String(scanId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getScanResults(namespace_, scanId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/scans/" + encodeURIComponent(String(scanId)) + "/results",
            params: [
                { key: "limit", value: opts.limit },
                { key: "offset", value: opts.offset }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getSnapshotJob(namespace_, jobId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/snapshot-jobs/" + encodeURIComponent(String(jobId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getTurbopufferNamespaceSchema(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/schema",
            params: undefined,
            fallback: { method: "GET", path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/schema" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getTurbopufferV1NamespaceMetadata(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/metadata",
            params: undefined,
            fallback: { method: "GET", path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/metadata" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getUdf(udfId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getUdfStatus(udfId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/status",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async getWarmJob(namespace_, jobId, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/warm-jobs/" + encodeURIComponent(String(jobId)),
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async heartbeatDocuments(pipelineId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/documents/heartbeat",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async heartbeatUdfItems(udfId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/items/heartbeat",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async hintCacheWarm(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/hint_cache_warm",
            params: [
                { key: "turbopuffer", value: opts.turbopuffer },
                { key: "documents", value: opts.documents },
                { key: "snapshots", value: opts.snapshots },
                { key: "page_size", value: opts.pageSize }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listClickstream(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/clickstream",
            params: [
                { key: "trace_id", value: opts.traceId },
                { key: "tag", value: opts.tags },
                { key: "from", value: opts.from_ },
                { key: "to", value: opts.to },
                { key: "before", value: opts.before },
                { key: "limit", value: opts.limit }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listKeys(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/keys",
            params: [
                { key: "includeRevoked", value: opts.includeRevoked }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listMetricsCatalog(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/catalog",
            params: [
                { key: "family", value: opts.family }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listNamespaceHistory(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/history",
            params: [
                { key: "limit", value: opts.limit },
                { key: "before", value: opts.before }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listNamespaces(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces",
            params: [
                { key: "prefix", value: opts.prefix },
                { key: "cursor", value: opts.cursor },
                { key: "page_size", value: opts.pageSize }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listPipelines(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/pipelines",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listScans(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/scans",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listSearchHistory(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/search-history",
            params: [
                { key: "tag", value: opts.tags },
                { key: "from", value: opts.from_ },
                { key: "to", value: opts.to },
                { key: "before", value: opts.before },
                { key: "limit", value: opts.limit }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listSnapshotActivity(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/activity/snapshots",
            params: [
                { key: "since", value: opts.since },
                { key: "limit", value: opts.limit },
                { key: "namespace", value: opts.namespace_ },
                { key: "cursor", value: opts.cursor }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listSnapshotJobs(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/snapshot-jobs",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listTurbopufferNamespaces(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v1/namespaces",
            params: [
                { key: "cursor", value: opts.cursor },
                { key: "prefix", value: opts.prefix },
                { key: "page_size", value: opts.pageSize }
            ],
            fallback: { method: "GET", path: "/v1/namespaces" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listUdfs(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/udfs",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async listWarmJobs(namespace_, opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/warm-jobs",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async mintKey(body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/keys",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async multiQueryTurbopufferNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query",
            params: [
                { key: "stainless_overload", value: "multiQuery" }
            ],
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async pauseUdf(udfId, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/pause",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async putPipelineDocumentChunks(pipelineId, docId, body, opts = {}) {
        return this.requestJson({
            method: "PUT",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/documents/" + encodeURIComponent(String(docId)),
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async putPipelineDocumentVectors(pipelineId, docId, body, opts = {}) {
        return this.requestJson({
            method: "PUT",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/documents/" + encodeURIComponent(String(docId)) + "/vectors",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryMetrics(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/query",
            params: [
                { key: "query", value: opts.query },
                { key: "time", value: opts.time },
                { key: "timeout", value: opts.timeout }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryMetricsApiV1(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/api/v1/query",
            params: [
                { key: "query", value: opts.query },
                { key: "time", value: opts.time },
                { key: "timeout", value: opts.timeout }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryMetricsRange(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/query_range",
            params: [
                { key: "query", value: opts.query },
                { key: "start", value: opts.start },
                { key: "end", value: opts.end },
                { key: "step", value: opts.step },
                { key: "timeout", value: opts.timeout }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryMetricsRangeApiV1(opts = {}) {
        return this.requestJson({
            method: "GET",
            path: "/v2/metrics/api/v1/query_range",
            params: [
                { key: "query", value: opts.query },
                { key: "start", value: opts.start },
                { key: "end", value: opts.end },
                { key: "step", value: opts.step },
                { key: "timeout", value: opts.timeout }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query",
            params: undefined,
            body: body,
            headers: this.searchHistoryHeaders(opts.searchQuery, opts.tags),
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query", transform: "query_namespace" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async queryTurbopufferNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query",
            params: undefined,
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/query" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async resetFailedUdf(udfId, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/reset-failed",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async resumeUdf(udfId, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/udfs/" + encodeURIComponent(String(udfId)) + "/resume",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async revokeKey(keyId, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/keys/" + encodeURIComponent(String(keyId)) + "/revoke",
            params: undefined,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async setDocumentsStage(pipelineId, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/pipelines/" + encodeURIComponent(String(pipelineId)) + "/documents/stage",
            params: undefined,
            body: body,
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async updateTurbopufferNamespaceMetadata(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "PATCH",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/metadata",
            params: undefined,
            body: body,
            fallback: { method: "PATCH", path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/metadata" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async updateTurbopufferNamespaceSchema(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/schema",
            params: undefined,
            body: body,
            fallback: { method: "POST", path: "/v1/namespaces/" + encodeURIComponent(String(namespace_)) + "/schema" },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async warmCache(namespace_, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) + "/warm",
            params: [
                { key: "page_size", value: opts.pageSize }
            ],
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async writeNamespace(namespace_, body, opts = {}) {
        return this.requestJson({
            method: "POST",
            path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)),
            params: undefined,
            body: body,
            fallback: { method: "POST", path: "/v2/namespaces/" + encodeURIComponent(String(namespace_)) },
            withPerf: opts.withPerf === true,
            signal: opts.signal,
        });
    }
    async ensurePipeline(body) {
        try {
            return await this.createPipeline(body);
        }
        catch (error) {
            if (!(error instanceof HevlayerError) || error.statusCode !== 409) {
                throw error;
            }
            const pipelineId = isRecord(body) ? body.id : undefined;
            const pipelines = await this.listPipelines();
            for (const pipeline of pipelines.pipelines ?? []) {
                if (String(pipeline.id) === String(pipelineId)) {
                    return pipeline;
                }
            }
            throw error;
        }
    }
    async releaseDocuments(pipelineId, documentIds, opts = {}) {
        return this.setDocumentsStageHelper(pipelineId, documentIds, "pending", opts);
    }
    async failDocuments(pipelineId, documentIds, opts = {}) {
        return this.setDocumentsStageHelper(pipelineId, documentIds, "failed", opts);
    }
    async completeDocuments(pipelineId, documentIds, opts = {}) {
        return this.setDocumentsStageHelper(pipelineId, documentIds, "indexed", opts);
    }
    async writeSingleVector(pipelineId, docId, vector, opts = {}) {
        return this.putPipelineDocumentVectors(pipelineId, docId, { vectors: [vector] }, opts);
    }
    async waitForScan(namespace, scanId, opts = {}) {
        const started = nowMs();
        let delay = opts.initialDelayMs ?? 50;
        const maxDelay = opts.maxDelayMs ?? 2000;
        while (true) {
            const scan = await this.getScan(namespace, scanId, { signal: opts.signal });
            if (scan.status === "completed" || scan.status === "failed") {
                return scan;
            }
            if (opts.timeoutMs !== undefined && nowMs() - started >= opts.timeoutMs) {
                throw new Error("scan " + JSON.stringify(scanId) + " did not finish within " + opts.timeoutMs + "ms");
            }
            await sleep(delay, opts.signal);
            delay = Math.min(delay * 2, maxDelay);
        }
    }
    async scan(namespace, body, opts = {}) {
        const created = await this.createScan(namespace, body, { signal: opts.signal });
        if (!isRecord(created) || typeof created.id !== "string") {
            throw new Error("scan create response did not include id");
        }
        return this.waitForScan(namespace, created.id, opts);
    }
    async warmNamespace(namespace, opts = {}) {
        return this.warmCache(namespace, opts);
    }
    async patchColumns(namespace, ids, attrs, opts = {}) {
        if (ids.length === 0) {
            throw new Error("patchColumns requires at least one id");
        }
        for (const id of ids) {
            if (!id) {
                throw new Error("patchColumns ids must be non-empty");
            }
        }
        const columns = { id: [...ids] };
        for (const [name, values] of Object.entries(attrs)) {
            if (name === "id") {
                throw new Error("patchColumns attrs must not include id");
            }
            if (values.length !== ids.length) {
                throw new Error("patchColumns attr " + JSON.stringify(name) + " has " + values.length + " values for " + ids.length + " ids");
            }
            columns[name] = [...values];
        }
        return this.writeNamespace(namespace, { patch_columns: columns }, opts);
    }
    async setDocumentsStageHelper(pipelineId, documentIds, stage, opts) {
        return this.setDocumentsStage(pipelineId, {
            document_ids: documentIds,
            stage,
            from_stage: opts.fromStage,
            worker_id: opts.workerId,
        }, opts);
    }
    async requestJson(request) {
        const started = nowMs();
        let response;
        try {
            response = await this.fetchJson(this.baseUrl, this.apiKey, request);
        }
        catch (error) {
            const originalError = unwrapTransportError(error);
            if (!request.fallback || !isTransportFallbackError(error)) {
                throw originalError;
            }
            return this.requestTurbopufferJson(originalError, started, request);
        }
        const latencyMs = nowMs() - started;
        const cacheStatus = response.headers.get("x-layer-cache");
        const raw = await this.decodeJsonResponse(response);
        if (!response.ok) {
            throw this.errorFromResponse(response, raw);
        }
        const data = raw;
        this.applyLayerHeaders(data, response.headers);
        if (request.withPerf) {
            return { data, perf: { latencyMs, cacheStatus, fallback: null } };
        }
        return data;
    }
    applyLayerHeaders(value, headers) {
        if (!isRecord(value)) {
            return;
        }
        const stable = headers.get("x-layer-stable-as-of");
        if (stable !== null) {
            const parsed = Number.parseInt(stable, 10);
            if (Number.isFinite(parsed)) {
                value.stable_as_of = parsed;
            }
        }
        const nextCursor = headers.get("x-layer-next-cursor");
        if (nextCursor !== null) {
            value.next_cursor = nextCursor;
        }
    }
    async requestBytes(request) {
        const started = nowMs();
        let response;
        try {
            response = await this.fetchJson(this.baseUrl, this.apiKey, request);
        }
        catch (error) {
            throw unwrapTransportError(error);
        }
        const latencyMs = nowMs() - started;
        const cacheStatus = response.headers.get("x-layer-cache");
        if (!response.ok) {
            throw this.errorFromResponse(response, await this.decodeJsonResponse(response));
        }
        const data = new Uint8Array(await response.arrayBuffer());
        if (request.withPerf) {
            return { data, perf: { latencyMs, cacheStatus, fallback: null } };
        }
        return data;
    }
    async requestTurbopufferJson(originalError, started, request) {
        if (!this.canFallbackToTurbopuffer() || !request.fallback) {
            throw originalError;
        }
        let body;
        try {
            body = this.fallbackBody(request.fallback, request.body);
        }
        catch {
            throw originalError;
        }
        console.warn("hevlayer gateway unreachable; falling through to Turbopuffer direct for " +
            request.fallback.method +
            " " +
            request.fallback.path);
        let response;
        try {
            response = await this.fetchJson(this.turbopufferBaseUrl, this.turbopufferApiKey, {
                method: request.fallback.method,
                path: request.fallback.path,
                params: request.params,
                body,
                signal: request.signal,
            });
        }
        catch (error) {
            throw unwrapTransportError(error);
        }
        const latencyMs = nowMs() - started;
        let raw = await this.decodeJsonResponse(response);
        if (!response.ok) {
            throw this.errorFromResponse(response, raw);
        }
        raw = this.fallbackResponse(request.fallback, raw);
        const data = raw;
        if (request.withPerf) {
            return { data, perf: { latencyMs, cacheStatus: null, fallback: "turbopuffer_direct" } };
        }
        return data;
    }
    async fetchJson(baseUrl, apiKey, request) {
        const headers = new Headers(request.headers);
        const init = {
            method: request.method,
            headers,
        };
        if (apiKey) {
            headers.set("Authorization", "Bearer " + apiKey);
        }
        if (request.body !== undefined && request.body !== null) {
            headers.set("Content-Type", "application/json");
            init.body = JSON.stringify(request.body);
        }
        const url = this.urlFor(baseUrl, request.path, request.params);
        const signal = this.requestSignal(request.signal);
        init.signal = signal.signal;
        try {
            return await this.fetchImpl(url, init);
        }
        catch (error) {
            throw new FetchTransportError(error);
        }
        finally {
            signal.cleanup();
        }
    }
    requestSignal(signal) {
        if (this.timeout === null && !signal) {
            return { cleanup: () => { } };
        }
        if (this.timeout === null) {
            return { signal, cleanup: () => { } };
        }
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeout);
        const abortFromSignal = () => controller.abort(signal?.reason);
        signal?.addEventListener("abort", abortFromSignal, { once: true });
        return {
            signal: controller.signal,
            cleanup: () => {
                clearTimeout(timeout);
                signal?.removeEventListener("abort", abortFromSignal);
            },
        };
    }
    urlFor(baseUrl, requestPath, params) {
        const url = new URL(requestPath, baseUrl + "/");
        for (const param of params ?? []) {
            const value = this.queryParamValue(param.key, param.value);
            if (value !== null) {
                url.searchParams.set(param.key, value);
            }
        }
        return url.toString();
    }
    queryParamValue(key, value) {
        if (value === undefined || value === null) {
            return null;
        }
        if (Array.isArray(value)) {
            if (value.length === 0) {
                return null;
            }
            if (key === "tag") {
                const tags = cleanHistoryTags(value);
                return tags.length ? tags.join(",") : null;
            }
            return value.map((item) => String(item)).join(",");
        }
        return String(value);
    }
    searchHistoryHeaders(searchQuery, tags) {
        const headers = {};
        if (searchQuery !== undefined) {
            const query = String(searchQuery).trim();
            if (query) {
                headers["x-hevlayer-search-query"] = query;
            }
        }
        if (tags !== undefined) {
            const cleanTags = cleanHistoryTags(tags);
            if (cleanTags.length > 0) {
                headers["x-hevlayer-tags"] = cleanTags.join(",");
            }
        }
        return Object.keys(headers).length ? headers : undefined;
    }
    canFallbackToTurbopuffer() {
        return this.fallbackToTurbopuffer && this.turbopufferApiKey !== null;
    }
    fallbackBody(fallback, value) {
        if (fallback.transform === "query_namespace") {
            return turbopufferQueryBody(value);
        }
        return value;
    }
    fallbackResponse(fallback, value) {
        if (fallback.transform === "query_namespace") {
            return queryResponseFromTurbopuffer(value);
        }
        return value;
    }
    async decodeJsonResponse(response) {
        if (response.status === 204) {
            return undefined;
        }
        const text = await response.text();
        if (!text) {
            return undefined;
        }
        try {
            return JSON.parse(text);
        }
        catch {
            return text;
        }
    }
    errorFromResponse(response, body) {
        if (isRecord(body)) {
            const kind = typeof body.error === "string" ? body.error : null;
            const message = typeof body.message === "string" && body.message ? body.message : response.statusText;
            return new HevlayerError(response.status, message, { kind, body, response });
        }
        const message = typeof body === "string" && body ? body : response.statusText;
        return new HevlayerError(response.status, message, { body, response });
    }
}
function defaultFetch() {
    if (typeof globalThis.fetch !== "function") {
        throw new Error("global fetch is unavailable; use Node 18+ or pass a fetch implementation");
    }
    return globalThis.fetch.bind(globalThis);
}
function env(name) {
    try {
        return typeof process !== "undefined" ? process.env?.[name] : undefined;
    }
    catch {
        return undefined;
    }
}
function cleanBaseUrl(value, fallback) {
    const cleaned = String(value ?? "").trim();
    return (cleaned || fallback).replace(/\/+$/, "");
}
function cleanToken(value) {
    const token = String(value ?? "").trim();
    return token ? token : null;
}
function cleanHistoryTags(tags) {
    const cleaned = [];
    for (const rawTag of tags) {
        const tag = String(rawTag).trim();
        if (!tag) {
            continue;
        }
        if (new TextEncoder().encode(tag).length > SEARCH_HISTORY_MAX_TAG_LENGTH) {
            throw new Error("search-history tag " + JSON.stringify(tag) + " exceeds " + SEARCH_HISTORY_MAX_TAG_LENGTH + " bytes");
        }
        if (!SEARCH_HISTORY_TAG_RE.test(tag)) {
            throw new Error("search-history tags may contain only ASCII letters, digits, ':', '_', '-', '.', '/', '=', or '+'; commas separate tags and cannot be escaped");
        }
        cleaned.push(tag);
    }
    const unique = [...new Set(cleaned)].sort();
    if (unique.length > SEARCH_HISTORY_MAX_TAGS) {
        throw new Error("search-history tags are limited to " + SEARCH_HISTORY_MAX_TAGS + " unique tags");
    }
    return unique;
}
function turbopufferQueryBody(value) {
    if (!isRecord(value)) {
        throw new Error("query fallback requires an object body");
    }
    if (value.nearest_to_id !== undefined && value.nearest_to_id !== null) {
        throw new Error("query fallback cannot resolve layer-only fields");
    }
    if (value.nearestToId !== undefined && value.nearestToId !== null) {
        throw new Error("query fallback cannot resolve layer-only fields");
    }
    if (value.cursor !== undefined && value.cursor !== null) {
        throw new Error("query fallback cannot resolve layer-only fields");
    }
    const vector = value.vector;
    if (!Array.isArray(vector) || vector.length === 0) {
        throw new Error("query fallback requires vector");
    }
    const body = {
        rank_by: ["vector", "ANN", vector],
        top_k: value.top_k ?? 10,
        consistency: { level: "eventual" },
    };
    if (value.filters !== undefined && value.filters !== null) {
        body.filters = value.filters;
    }
    if (value.include_attributes !== undefined && value.include_attributes !== null) {
        body.include_attributes = value.include_attributes;
    }
    return body;
}
function queryResponseFromTurbopuffer(value) {
    return isRecord(value) ? value : {};
}
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isTransportFallbackError(error) {
    if (!(error instanceof FetchTransportError)) {
        return false;
    }
    if (error.cause instanceof DOMException && error.cause.name === "AbortError") {
        return false;
    }
    return true;
}
function unwrapTransportError(error) {
    return error instanceof FetchTransportError ? error.cause : error;
}
function nowMs() {
    return typeof performance !== "undefined" ? performance.now() : Date.now();
}
function sleep(ms, signal) {
    if (signal?.aborted) {
        return Promise.reject(signal.reason);
    }
    return new Promise((resolve, reject) => {
        const timeout = setTimeout(resolve, ms);
        const abort = () => {
            clearTimeout(timeout);
            reject(signal?.reason);
        };
        signal?.addEventListener("abort", abort, { once: true });
    });
}
//# sourceMappingURL=client.js.map