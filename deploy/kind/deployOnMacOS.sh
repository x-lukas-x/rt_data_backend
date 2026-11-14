#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
calico_manifest="https://raw.githubusercontent.com/projectcalico/calico/v3.29.2/manifests/calico.yaml"
required_commands=(docker kind kubectl)
missing_commands=()

for command_name in "${required_commands[@]}"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        missing_commands+=("$command_name")
    fi
done

if ((${#missing_commands[@]} > 0)); then
    printf 'Missing required command(s): %s. Install Docker Desktop, kubectl, and Kind as described in README_MacOS.md.\n' \
        "${missing_commands[*]}" >&2
    exit 1
fi

if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
    echo "Docker is installed but its engine is not running. Start Docker Desktop and retry." >&2
    exit 1
fi

cd "$repo_root"

docker build -t rt-data-backend:local . || {
    echo "Docker image build failed." >&2
    exit 1
}

clusters="$(kind get clusters)" || {
    echo "Could not query Kind clusters. Check the Kind installation." >&2
    exit 1
}
if ! grep -Fxq "rt-data" <<<"$clusters"; then
    kind create cluster --config deploy/kind/kind-config.yaml || {
        echo "Kind cluster creation failed." >&2
        exit 1
    }
fi

kind load docker-image rt-data-backend:local --name rt-data || {
    echo "Could not load the application image into Kind." >&2
    exit 1
}
kubectl config use-context kind-rt-data || {
    echo "Could not select the kind-rt-data kubectl context." >&2
    exit 1
}

kubectl apply -f "$calico_manifest" || {
    echo "Calico installation failed." >&2
    exit 1
}
kubectl wait --for=condition=Ready pod -l k8s-app=calico-node -n kube-system --timeout=300s || {
    echo "Calico did not become ready." >&2
    exit 1
}

kubectl apply -f deploy/kind/00-namespaces.yaml || {
    echo "Could not create project namespaces." >&2
    exit 1
}
kubectl apply -f deploy/kind/10-infrastructure.yaml || {
    echo "Could not deploy PostgreSQL and Kafka." >&2
    exit 1
}
kubectl rollout status statefulset/postgres -n database --timeout=300s || {
    echo "PostgreSQL did not become ready." >&2
    exit 1
}
kubectl rollout status statefulset/kafka -n streaming --timeout=300s || {
    echo "Kafka did not become ready." >&2
    exit 1
}
kubectl wait --for=condition=complete job/kafka-init -n streaming --timeout=180s || {
    echo "Kafka topic initialization failed." >&2
    exit 1
}

kubectl apply -f deploy/kind/20-data-services.yaml || {
    echo "Could not deploy the inventory service and CSV importer." >&2
    exit 1
}
kubectl wait --for=condition=complete job/csv-import -n database --timeout=300s || {
    echo "The initial CSV import failed." >&2
    exit 1
}

kubectl apply -f deploy/kind/90-network-policies.yaml || {
    echo "Could not apply Kubernetes NetworkPolicies." >&2
    exit 1
}
kubectl apply -f deploy/kind/30-applications.yaml || {
    echo "Could not deploy application workloads." >&2
    exit 1
}

for namespace in database streaming processing shop-a shop-b shop-n; do
    kubectl wait --for=condition=Available deployment --all -n "$namespace" --timeout=300s || {
        printf 'A Deployment did not become available in namespace %s.\n' "$namespace" >&2
        exit 1
    }
done

echo "Setup complete. Gateway: http://localhost:8080"
