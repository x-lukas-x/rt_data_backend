$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$calicoManifest = "https://raw.githubusercontent.com/projectcalico/calico/v3.29.2/manifests/calico.yaml"

$requiredCommands = @("docker", "kind", "kubectl")
$missingCommands = @(
    $requiredCommands | Where-Object {
        -not (Get-Command $_ -ErrorAction SilentlyContinue)
    }
)
if ($missingCommands.Count -gt 0) {
    throw "Missing required command(s): $($missingCommands -join ', '). Follow the 'Install kubectl and Kind' section in README.md; install Docker Desktop separately."
}

$null = docker --version
if ($LASTEXITCODE -ne 0) {
    throw "Could not run the Docker CLI. Check your Docker installation and PATH."
}
$null = kind version
if ($LASTEXITCODE -ne 0) {
    throw "Could not run kind. Check your Kind installation and PATH."
}
$null = kubectl version --client
if ($LASTEXITCODE -ne 0) {
    throw "Could not run kubectl. Check your kubectl installation and PATH."
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its engine is not running. Start Docker Desktop and wait for the Linux engine, then retry."
}

Push-Location $repoRoot
try {
    docker build -t rt-data-backend:local .
    if ($LASTEXITCODE -ne 0) { throw "Docker image build failed." }

    $clusters = kind get clusters
    if ($LASTEXITCODE -ne 0) { throw "Could not query Kind clusters. Is kind installed?" }
    if ($clusters -notcontains "rt-data") {
        kind create cluster --config deploy/kind/kind-config.yaml
        if ($LASTEXITCODE -ne 0) { throw "Kind cluster creation failed." }
    }

    kind load docker-image rt-data-backend:local --name rt-data
    if ($LASTEXITCODE -ne 0) { throw "Could not load the application image into Kind." }

    kubectl config use-context kind-rt-data
    if ($LASTEXITCODE -ne 0) { throw "Could not select the kind-rt-data kubectl context." }

    kubectl apply -f $calicoManifest
    if ($LASTEXITCODE -ne 0) { throw "Calico installation failed." }
    kubectl wait --for=condition=Ready pod -l k8s-app=calico-node -n kube-system --timeout=300s
    if ($LASTEXITCODE -ne 0) { throw "Calico did not become ready." }

    kubectl apply -f deploy/kind/00-namespaces.yaml
    if ($LASTEXITCODE -ne 0) { throw "Could not create project namespaces." }
    kubectl apply -f deploy/kind/10-infrastructure.yaml
    if ($LASTEXITCODE -ne 0) { throw "Could not deploy PostgreSQL and Kafka." }
    kubectl rollout status statefulset/postgres -n database --timeout=300s
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not become ready." }
    kubectl rollout status statefulset/kafka -n streaming --timeout=300s
    if ($LASTEXITCODE -ne 0) { throw "Kafka did not become ready." }
    kubectl wait --for=condition=complete job/kafka-init -n streaming --timeout=180s
    if ($LASTEXITCODE -ne 0) { throw "Kafka topic initialization failed." }

    kubectl apply -f deploy/kind/20-data-services.yaml
    if ($LASTEXITCODE -ne 0) { throw "Could not deploy the inventory service and CSV importer." }
    kubectl wait --for=condition=complete job/csv-import -n database --timeout=300s
    if ($LASTEXITCODE -ne 0) { throw "The initial CSV import failed." }

    kubectl apply -f deploy/kind/90-network-policies.yaml
    if ($LASTEXITCODE -ne 0) { throw "Could not apply Kubernetes NetworkPolicies." }
    kubectl apply -f deploy/kind/30-applications.yaml
    if ($LASTEXITCODE -ne 0) { throw "Could not deploy application workloads." }

    foreach ($namespace in @("database", "streaming", "processing", "shop-a", "shop-b", "shop-n")) {
        kubectl wait --for=condition=Available deployment --all -n $namespace --timeout=300s
        if ($LASTEXITCODE -ne 0) { throw "A Deployment did not become available in namespace $namespace." }
    }

    Write-Host "Setup complete. Gateway: http://localhost:8080"
}
finally {
    Pop-Location
}