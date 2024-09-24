output "app_name" {
  value = juju_application.knative_eventing.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    otel_collector = "otel-collector"
  }
}
