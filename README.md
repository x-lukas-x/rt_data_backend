# Grocery Inventory Test Project

A local test project running on a fixed Kind cluster with three shops, Kafka, and PostgreSQL. The shops generate sales automatically. When a sale reduces stock from 10 to 9, a warning is sent to the shop that caused the threshold crossing, followed by an idempotent restock order for 100 units.

## Prerequisites

- Windows 10/11 x64 with hardware virtualization enabled in BIOS/UEFI.
- Docker Desktop installed and running with its Linux engine.
- PowerShell and `curl.exe` (included with current Windows 10/11 releases).

For macOS, use the separate [macOS setup guide](README_MacOS.md), which includes a macOS deployment script.

## Install kubectl and Kind

Open PowerShell in the repository directory. Administrator privileges are not required because the tools are installed under your user profile:

```powershell
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\GroceryInventory\bin'
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

curl.exe -fL 'https://dl.k8s.io/release/v1.33.0/bin/windows/amd64/kubectl.exe' `
    -o (Join-Path $installDir 'kubectl.exe')
curl.exe -fL 'https://kind.sigs.k8s.io/dl/v0.29.0/kind-windows-amd64' `
    -o (Join-Path $installDir 'kind.exe')

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @($userPath -split ';' | Where-Object { $_ })
if ($pathEntries -notcontains $installDir) {
    [Environment]::SetEnvironmentVariable('Path', "$installDir;$userPath", 'User')
}
$env:Path = "$installDir;$env:Path"

kubectl version --client
kind version
```

The commands download the official Windows x64 binaries for kubectl `1.33.0` and Kind `0.29.0`. Open a new PowerShell window if you want the updated user PATH to be available there as well.

## Start the Kind Cluster

If PowerShell blocks the deployment script, allow locally created scripts for your user (no administrator privileges required):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Make sure Docker Desktop is running, then run:

```powershell
.\deploy\kind\deploy.ps1
```

The deployment creates one control plane and three worker nodes, installs Calico, imports all 990 products from `data/Grocery_Inventory_Dataset.csv` exactly once, and starts the workloads. It preserves each CSV `Product_ID` and adds 10 to every positive initial stock value. The gateway is available at `http://localhost:8080`.

## Verify the Project

The interactive API documentation is available at [http://localhost:8080/docs](http://localhost:8080/docs). Useful endpoints:

| Purpose | Endpoint |
| --- | --- |
| Gateway readiness | [http://localhost:8080/health/ready](http://localhost:8080/health/ready) |
| Products and stock | [http://localhost:8080/products](http://localhost:8080/products) |
| Products in stock | [http://localhost:8080/products?in_stock=true](http://localhost:8080/products?in_stock=true) |
| A single product | `http://localhost:8080/products/{product_id}` |
| Market sales total | [http://localhost:8080/market/sales/total](http://localhost:8080/market/sales/total) |
| Shop A sales total | [http://localhost:8080/shops/shop-a/sales/total](http://localhost:8080/shops/shop-a/sales/total) |
| Shop B sales total | [http://localhost:8080/shops/shop-b/sales/total](http://localhost:8080/shops/shop-b/sales/total) |
| Shop N sales total | [http://localhost:8080/shops/shop-n/sales/total](http://localhost:8080/shops/shop-n/sales/total) |
| Event/order status | `http://localhost:8080/orders/{event_id}` |

`POST /events` returns `202` when Kafka has received the event. This does not mean the sale or restock has been processed; query `/orders/{event_id}` for its status.

## Inspect Pods and Traffic

List all Pods across namespaces:

```powershell
kubectl get pods -A -o wide
```

Follow the sales processor and Shop A revenue poller logs:

```powershell
kubectl logs -n processing deployment/sales-processor -f
kubectl logs -n shop-a deployment/revenue-poller -f
```

Read incoming shop events from Kafka:

```powershell
kubectl exec -n streaming kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic shop-events
```

Press `Ctrl+C` to stop the Kafka consumer. Query the sales endpoints again to see the totals change.

## Pause or Delete the Cluster

Scale down the Deployments and StatefulSets to pause the workloads while retaining persistent data:

```powershell
$namespaces = @('shop-a', 'shop-b', 'shop-n', 'streaming', 'processing', 'database')
foreach ($namespace in $namespaces) {
    kubectl scale deployment --all --replicas=0 -n $namespace
}
kubectl scale statefulset kafka --replicas=0 -n streaming
kubectl scale statefulset postgres --replicas=0 -n database
```

Delete the entire Kind cluster and its local data:

```powershell
kind delete cluster --name rt-data
```

This project uses single Kafka and PostgreSQL instances with local demo credentials. It is intended for testing, not production use.