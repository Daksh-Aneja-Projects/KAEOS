{{- define "kaeos.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "kaeos.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "kaeos.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "kaeos.labels" -}}
app.kubernetes.io/name: {{ include "kaeos.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "kaeos.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "kaeos.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Resolve a component image ref: per-component override, else global repo suffix, else appVersion. */}}
{{- define "kaeos.image" -}}
{{- $root := index . 0 -}}
{{- $comp := index . 1 -}}
{{- $g := $root.Values.image -}}
{{- $repo := $comp.image.repository | default (printf "%s-%s" $g.repository (index . 2)) -}}
{{- $tag := $comp.image.tag | default $g.tag | default $root.Chart.AppVersion -}}
{{- printf "%s/%s:%s" $g.registry $repo $tag -}}
{{- end -}}
