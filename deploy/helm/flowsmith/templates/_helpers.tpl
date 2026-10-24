{{/*
Expand the chart name.
*/}}
{{- define "flowsmith.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a fully qualified release name.
*/}}
{{- define "flowsmith.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "flowsmith.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "flowsmith.labels" -}}
helm.sh/chart: {{ include "flowsmith.chart" . }}
{{ include "flowsmith.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "flowsmith.selectorLabels" -}}
app.kubernetes.io/name: {{ include "flowsmith.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "flowsmith.componentLabels" -}}
{{ include "flowsmith.selectorLabels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "flowsmith.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "flowsmith.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "flowsmith.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "flowsmith.fullname" .) }}
{{- end }}
{{- end }}

{{- define "flowsmith.configMapName" -}}
{{- printf "%s-config" (include "flowsmith.fullname" .) }}
{{- end }}

{{- define "flowsmith.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{- define "flowsmith.databaseUrl" -}}
{{- if .Values.externalDatabase.url }}
{{- .Values.externalDatabase.url }}
{{- else if .Values.postgresql.enabled }}
{{- $password := required "postgresql.password is required when postgresql.enabled=true" .Values.postgresql.password }}
{{- printf "postgresql://%s:%s@%s-postgresql:5432/%s" .Values.postgresql.auth.username (urlquery $password) (include "flowsmith.fullname" .) .Values.postgresql.auth.database }}
{{- else }}
{{- required "externalDatabase.url is required when postgresql.enabled=false" .Values.externalDatabase.url }}
{{- end }}
{{- end }}

{{- define "flowsmith.redisUrl" -}}
{{- if .Values.externalRedis.url }}
{{- .Values.externalRedis.url }}
{{- else if .Values.redis.enabled }}
{{- $password := required "redis.password is required when redis.enabled=true" .Values.redis.password }}
{{- printf "redis://:%s@%s-redis:6379/0" (urlquery $password) (include "flowsmith.fullname" .) }}
{{- else }}
{{- required "externalRedis.url is required when redis.enabled=false" .Values.externalRedis.url }}
{{- end }}
{{- end }}

{{- define "flowsmith.dataClaimName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-data" (include "flowsmith.fullname" .) }}
{{- end }}
{{- end }}

{{- define "flowsmith.checksumConfig" -}}
{{- include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- end }}

{{- define "flowsmith.checksumSecret" -}}
{{- if .Values.secrets.create }}
{{- include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
{{- else }}
{{- .Values.secrets.existingSecret | sha256sum }}
{{- end }}
{{- end }}
