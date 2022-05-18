from lightkube.generic_resource import create_namespaced_resource

# Knative Operator's KnativeServing CRDs
KnativeServing_v1alpha1 = create_namespaced_resource(
    group="operator.knative.dev",
    version="v1alpha1",
    kind="KnativeServing",
    plural="knativeservings",
    verbs=None
)
# v1.3 and above
KnativeServing_v1beta1 = create_namespaced_resource(
    group="operator.knative.dev",
    version="v1beta1",
    kind="KnativeServing",
    plural="knativeservings",
    verbs=None
)

# Knative Operator's KnativeEventing CRDs
KnativeEventing_v1beta1 = create_namespaced_resource(
    group="operator.knative.dev",
    version="v1beta1",
    kind="KnativeEventing",
    plural="knativeeventings",
    verbs=None
)
