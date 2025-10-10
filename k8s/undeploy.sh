#!/bin/bash

# KuzuScale Kubernetes Undeploy Script
# This script removes the complete KuzuScale cluster deployment

set -e

echo "🗑️  Starting KuzuScale Kubernetes Undeploy"

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

# Function to safely delete resource
safe_delete() {
    local resource=$1
    local file=$2
    if kubectl get $resource -n kuzu-scale &> /dev/null; then
        echo "🗑️  Deleting $resource..."
        kubectl delete -f $file --ignore-not-found=true
    else
        echo "ℹ️  $resource not found, skipping..."
    fi
}

# Delete monitoring stack first
echo "📊 Removing monitoring stack..."
safe_delete "deployment/grafana" "monitoring/grafana-deployment.yaml"
safe_delete "configmap/grafana-dashboards" "monitoring/grafana-dashboards.yaml"
safe_delete "configmap/grafana-dashboards-config" "monitoring/grafana-dashboards-config.yaml"
safe_delete "configmap/grafana-datasources" "monitoring/grafana-datasources.yaml"
safe_delete "deployment/prometheus" "monitoring/prometheus-deployment.yaml"
safe_delete "configmap/prometheus-config" "monitoring/prometheus-config.yaml"

# Delete main application
echo "🏗️  Removing KuzuScale application..."
safe_delete "ingress/kuzu-scale-ingress" "ingress.yaml"
safe_delete "hpa/kuzu-scale-hpa" "hpa.yaml"
safe_delete "service/kuzu-scale-service" "service.yaml"
safe_delete "deployment/kuzu-scale" "deployment.yaml"

# Delete persistent volumes (with confirmation)
echo "💾 Removing persistent storage..."
read -p "⚠️  Do you want to delete persistent volumes? This will remove all data! (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    safe_delete "pvc/kuzu-scale-data-pvc" "persistent-volume.yaml"
    safe_delete "pvc/grafana-pvc" "monitoring/grafana-deployment.yaml"
    echo "💾 Persistent volumes deleted"
else
    echo "💾 Persistent volumes preserved"
fi

# Delete configs and secrets
echo "🔐 Removing configurations and secrets..."
safe_delete "configmap/kuzu-scale-config" "configmap.yaml"
safe_delete "secret/kuzu-scale-secrets" "secret.yaml"

# Delete namespace (this will clean up any remaining resources)
echo "📦 Removing namespace..."
if kubectl get namespace kuzu-scale &> /dev/null; then
    kubectl delete namespace kuzu-scale --timeout=60s
    echo "📦 Namespace deleted"
else
    echo "ℹ️  Namespace not found, skipping..."
fi

echo ""
echo "🎉 KuzuScale undeploy completed successfully!"
echo ""
echo "📋 Cleanup Summary:"
echo "=================="
echo "✅ All KuzuScale resources removed"
echo "✅ Monitoring stack removed"
echo "✅ Namespace deleted"
echo ""
echo "📝 Manual Cleanup (if needed):"
echo "=============================="
echo "1. Remove /etc/hosts entries:"
echo "   kuzu-scale.local"
echo "   grafana.kuzu-scale.local"
echo "   prometheus.kuzu-scale.local"
echo ""
echo "2. Verify no resources remain:"
echo "   kubectl get all --all-namespaces | grep kuzu"