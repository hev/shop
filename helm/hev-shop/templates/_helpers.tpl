{{- define "hev-shop.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hev-shop.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "hev-shop.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hev-shop.labels" -}}
helm.sh/chart: {{ include "hev-shop.chart" . }}
app.kubernetes.io/name: {{ include "hev-shop.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "hev-shop.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hev-shop.name" . }}
{{- end -}}

{{- define "hev-shop.configName" -}}
{{- printf "%s-config" (include "hev-shop.fullname" .) -}}
{{- end -}}

{{- define "hev-shop.secretName" -}}
{{- default (printf "%s-secrets" (include "hev-shop.fullname" .)) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "hev-shop.pvcName" -}}
{{- default (printf "%s-data" (include "hev-shop.fullname" .)) .Values.persistence.existingClaim -}}
{{- end -}}

{{- /*
  Indexer control plane image — the `api` target of indexer/Dockerfile.
  Worker images (extract-chunk/embed targets) are referenced by the Pipeline
  resources in indexer/pipelines/, not by this chart.
*/ -}}
{{- define "hev-shop.indexerImage" -}}
{{- printf "%s:%s" .Values.indexerImage.repository (.Values.indexerImage.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- /*
  Search read-API image. CLIP-text only. Built from search/Dockerfile.
*/ -}}
{{- define "hev-shop.searchImage" -}}
{{- printf "%s:%s" .Values.searchImage.repository (.Values.searchImage.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- define "hev-shop.webImage" -}}
{{- printf "%s:%s" .Values.webImage.repository (.Values.webImage.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- /*
  LAYER_GATEWAY_API_KEY env entry, shared by search / indexer-api / web.

  By default it is sourced from the Layer-managed gateway secret
  (secrets.gatewayKeySecret / gatewayKeySecretKey) via secretKeyRef, so a
  hev-shop `helm upgrade` can never blank it: the live secret is the single
  source of truth — the same one the gateway and the operator-generated
  warm-blobs worker use. (The 2026-06-24 outage was a deploy that rendered the
  key from the empty `layerApiKey` default and 401'd every read.)

  optional:true preserves the local-dev "no key -> gateway middleware no-op"
  case. Set gatewayKeySecret: "" to fall back to the chart's own secret carrying
  secrets.layerApiKey (offline / self-contained installs).
*/ -}}
{{- define "hev-shop.gatewayApiKeyEnv" -}}
- name: LAYER_GATEWAY_API_KEY
  valueFrom:
    secretKeyRef:
{{- if .Values.secrets.gatewayKeySecret }}
      name: {{ .Values.secrets.gatewayKeySecret | quote }}
      key: {{ .Values.secrets.gatewayKeySecretKey | quote }}
      optional: true
{{- else }}
      name: {{ include "hev-shop.secretName" . }}
      key: LAYER_GATEWAY_API_KEY
{{- end }}
{{- end -}}
