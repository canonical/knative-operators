output "app_name" {
  value = juju_application.knative_serving.name
}

output "provides" {
  value = {
    ingress_gateway = "ingress-gateway",
    local_gateway = "local-gateway"
  }
}

output "requires" {
  value = {
    otel_collector = "otel-collector"
  }
}
