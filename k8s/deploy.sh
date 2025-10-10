#!/bin/bash

# KuzuScale Kubernetes Deployment Script
# This script deploys the complete KuzuScale cluster with monitoring

set -e

echo "🚀 Starting KuzuScale Kubernetes Deployment"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl is not installed or not in PATH"
    exit 1
fi

# Check if cluster is accessible
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes cluster"
    exit 1
fi

echo "✅ Kubernetes cluster is accessible"

# Function to wait for deployment to be ready
wait_for_deployment() {
    local deployment=$1
    local namespace=$2
    echo "⏳ Waiting for deployment $deployment to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/$deployment -n $namespace
    echo "✅ Deployment $deployment is ready"
}

# Function to wait for service to be ready
wait_for_service() {
    local service=$1
    local namespace=$2
    echo "⏳ Waiting for service $service to be ready..."
    kubectl wait --for=condition=ready --timeout=300s service/$service -n $namespace || true
    echo "✅ Service $service is ready"
}

# Create namespace
echo "📦 Creating namespace..."
kubectl apply -f namespace.yaml

# Apply secrets and configs
echo "🔐 Applying secrets and configurations..."
kubectl apply -f secret.yaml
kubectl apply -f configmap.yaml

# Apply persistent volumes
echo "💾 Setting up persistent storage..."
kubectl apply -f persistent-volume.yaml

# Deploy main application
echo "🏗️  Deploying KuzuScale application..."
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# Deploy HPA
echo "📈 Setting up horizontal pod autoscaler..."
kubectl apply -f hpa.yaml

# Deploy ingress
echo "🌐 Setting up ingress..."
kubectl apply -f ingress.yaml

# Wait for main application to be ready
wait_for_deployment "kuzu-scale" "kuzu-scale"
wait_for_service "kuzu-scale-service" "kuzu-scale"

# Deploy monitoring stack
echo "📊 Deploying monitoring stack..."

# Prometheus
echo "📈 Deploying Prometheus..."
kubectl apply -f monitoring/prometheus-config.yaml
kubectl apply -f monitoring/prometheus-deployment.yaml
wait_for_deployment "prometheus" "kuzu-scale"

# Grafana
echo "📊 Deploying Grafana..."
kubectl apply -f monitoring/grafana-datasources.yaml
kubectl apply -f monitoring/grafana-dashboards-config.yaml
kubectl apply -f monitoring/grafana-dashboards.yaml
kubectl apply -f monitoring/grafana-deployment.yaml
wait_for_deployment "grafana" "kuzu-scale"

echo "🎉 KuzuScale deployment completed successfully!"

# Display useful information
echo ""
echo "📋 Deployment Summary:"
echo "======================"
kubectl get pods -n kuzu-scale
echo ""
echo "🔗 Service Information:"
echo "======================"
kubectl get services -n kuzu-scale
echo ""
echo "🌍 Ingress Information:"
echo "======================"
kubectl get ingress -n kuzu-scale
echo ""

# Display access information
echo "🔗 Access Information:"
echo "====================="
echo "KuzuScale API: http://kuzu-scale.local"
echo "Grafana Dashboard: http://grafana.kuzu-scale.local"
echo "Prometheus: http://prometheus.kuzu-scale.local"
echo ""
echo "📝 Next Steps:"
echo "=============="
echo "1. Add the following entries to your /etc/hosts file:"
echo "   <CLUSTER_IP> kuzu-scale.local"
echo "   <CLUSTER_IP> grafana.kuzu-scale.local"
echo "   <CLUSTER_IP> prometheus.kuzu-scale.local"
echo ""
echo "2. Access Grafana with admin/admin (change password on first login)"
echo ""
echo "3. Monitor cluster health:"
echo "   kubectl get pods -n kuzu-scale --watch"
echo ""
echo "4. View logs:"
echo "   kubectl logs -f deployment/kuzu-scale -n kuzu-scale"
echo "   kubectl logs -f deployment/prometheus -n kuzu-scale"
echo "   kubectl logs -f deployment/grafana -n kuzu-scale"

echo ""
echo "✅ KuzuScale is now ready for production workloads!"