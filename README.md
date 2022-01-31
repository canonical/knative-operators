# Charmed Knative Operators

Knative is a Kubernetes-based platform to deploy and manage modern serverless workloads.

For more details of what is possible with Knative, see https://knative.dev/


## Install

``` yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: knative-controller
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: knative-activator-operator
  namespace: knative-serving
- kind: ServiceAccount
  name: knative-autoscaler-operator
  namespace: knative-serving
- kind: ServiceAccount
  name: knative-controller-operator
  namespace: knative-serving
- kind: ServiceAccount
  name: knative-webhook-operator
  namespace: knative-serving
```
