output "app_name" {
  value = juju_application.knative_operator.name
}

output "provides" {
  value = {
    otel_collector   = "otel-collector"
    metrics_endpoint = "metrics-endpoint"
  }
}

output "requires" {
  value = {
    logging = "logging"
  }
}
