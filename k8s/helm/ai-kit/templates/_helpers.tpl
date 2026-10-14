{{- define "ai-kit.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ai-kit.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{{ end }}
{{- end }}
{{- end }}

{{- define "ai-kit.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/part-of: ai-kit
{{- end }}

{{- define "ai-kit.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ai-kit.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ai-kit.apiSelectorLabels" -}}
{{ include "ai-kit.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{- define "ai-kit.webSelectorLabels" -}}
{{ include "ai-kit.selectorLabels" . }}
app.kubernetes.io/component: web
{{- end }}

{{- define "ai-kit.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}{{ default (include "ai-kit.fullname" .) .Values.serviceAccount.name }}{{- else }}{{ default "default" .Values.serviceAccount.name }}{{- end }}
{{- end }}
