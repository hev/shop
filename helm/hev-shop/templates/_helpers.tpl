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
  Worker + indexer control plane image. Bakes both CLIP-image and Qwen-8B
  by default — workers need both. Built from indexer/Dockerfile.
*/ -}}
{{- define "hev-shop.indexerImage" -}}
{{- printf "%s:%s" .Values.indexerImage.repository (.Values.indexerImage.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- /*
  Search read-API image. CLIP-text only — Qwen-8B is off by default in the
  search Dockerfile because the search pod runs on the small infra node and
  never loads Qwen on CPU (review search returns 503 unless the pod has a
  GPU). Built from search/Dockerfile.
*/ -}}
{{- define "hev-shop.searchImage" -}}
{{- printf "%s:%s" .Values.searchImage.repository (.Values.searchImage.tag | default .Chart.AppVersion) -}}
{{- end -}}

{{- define "hev-shop.webImage" -}}
{{- printf "%s:%s" .Values.webImage.repository (.Values.webImage.tag | default .Chart.AppVersion) -}}
{{- end -}}
