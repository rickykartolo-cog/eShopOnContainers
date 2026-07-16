#!/usr/bin/env bash
# Shared service inventory for contract tooling.
# Ports match src/docker-compose.override.yml host mappings.

# service_name:host_port:has_swagger
SERVICES=(
  "catalog:5101:yes"
  "ordering:5102:yes"
  "basket:5103:yes"
  "identity:5105:no"
  "payment:5108:no"
  "locations:5109:yes"
  "marketing:5110:yes"
  "ordering-signalrhub:5112:no"
  "webhooks:5113:yes"
)
