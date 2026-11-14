# Grocery Inventory Test Project on macOS

This guide covers running the project locally on macOS. For Windows, see [README.md](README.md).

## Prerequisites

- macOS on Intel or Apple Silicon
- Docker Desktop for Mac installed and running with its Linux engine
- Homebrew

On Apple Silicon, Docker Desktop and the container images must support `arm64`. The Dockerfile and the images used by this project are built/pulled for the host architecture by default. If an image does not provide an `arm64` variant, resolve that image compatibility before deploying; emulation can be slower.

## Install kubectl and Kind

Install the Kubernetes command-line tools with Homebrew:

```bash
brew install kubectl kind
```

Check that Docker Desktop is running, then verify the tools:

```bash
docker --version
docker info
kubectl version --client
kind version
```

## Start the Kind Cluster

From the repository root, run the deployment script:

```bash
chmod +x deploy/kind/deployOnMacOS.sh
./deploy/kind/deployOnMacOS.sh
```

The script builds the application image locally, creates the `rt-data` Kind cluster if it does not already exist, loads the image into the cluster, installs Calico, and deploys the services. It imports all 990 products from `data/Grocery_Inventory_Dataset.csv` exactly once, preserves each CSV `Product_ID`, and adds 10 to every positive initial stock value. The gateway is available at [http://localhost:8080](http://localhost:8080).

If a deployment step fails, the script stops and prints an error. Check that Docker Desktop is running and has enough CPU, memory, and disk space, then fix the reported issue before running it again.

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

```bash
kubectl get pods -A -o wide
```

Follow the sales processor and Shop A revenue poller logs:

```bash
kubectl logs -n processing deployment/sales-processor -f
kubectl logs -n shop-a deployment/revenue-poller -f
```

Read incoming shop events from Kafka:

```bash
kubectl exec -n streaming kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic shop-events
```

Press `Ctrl+C` to stop the Kafka consumer. Query the sales endpoints again to see the totals change.

## Pause or Delete the Cluster

Scale down the Deployments and StatefulSets to pause the workloads while retaining persistent data:

```bash
for namespace in shop-a shop-b shop-n streaming processing database; do
    kubectl scale deployment --all --replicas=0 -n "$namespace"
done
kubectl scale statefulset kafka --replicas=0 -n streaming
kubectl scale statefulset postgres --replicas=0 -n database
```

Delete the entire Kind cluster and its local data:

```bash
kind delete cluster --name rt-data
```

This project uses single Kafka and PostgreSQL instances with local demo credentials. It is intended for testing, not production use.
