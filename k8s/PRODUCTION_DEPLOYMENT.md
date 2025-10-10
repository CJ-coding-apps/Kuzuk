# Kuzuk Production Deployment Guide

This guide provides step-by-step instructions for deploying Kuzuk in a production Kubernetes environment.

## Prerequisites

### System Requirements
- Kubernetes cluster v1.20+ with RBAC enabled
- kubectl configured and authenticated
- Minimum 4 CPU cores and 8GB RAM per node
- Persistent storage provider (NFS, SAN, or cloud storage)
- Load balancer or ingress controller (nginx, Istio, etc.)

### Required Tools
- `kubectl` - Kubernetes command-line tool
- `helm` (optional) - For advanced deployments
- `docker` - For building custom images

## Pre-Deployment Checklist

### 1. Cluster Verification
```bash
# Verify cluster access
kubectl cluster-info

# Check node resources
kubectl get nodes -o wide

# Verify storage classes
kubectl get storageclass

# Check ingress controller
kubectl get pods -n ingress-nginx  # or your ingress namespace
```

### 2. Resource Planning
- **CPU**: 2-4 cores per Kuzuk pod (adjust based on workload)
- **Memory**: 4-8GB per Kuzuk pod
- **Storage**: 
  - Primary database: 100GB+ SSD storage
  - WAL files: 20GB+ fast storage
  - Prometheus metrics: 20GB+ storage
  - Grafana dashboards: 1GB storage

### 3. Network Configuration
- Ensure cluster networking supports pod-to-pod communication
- Configure firewall rules for required ports:
  - 8000: Kuzuk API
  - 9090: Prometheus
  - 3000: Grafana
- Set up DNS resolution for ingress hostnames

## Deployment Steps

### 1. Environment Preparation
```bash
# Clone the repository
git clone <repository-url>
cd Kuzuk_001/k8s

# Review and customize configuration
vim secret.yaml          # Update passwords and secrets
vim configmap.yaml       # Adjust application settings
vim deployment.yaml      # Review resource limits
```

### 2. Security Configuration

#### Update Secrets (CRITICAL)
```bash
# Generate secure passwords
openssl rand -base64 32  # For database passwords
openssl rand -base64 32  # For Grafana admin password

# Edit secret.yaml with generated passwords
vim secret.yaml
```

#### Network Policies (Recommended)
```bash
# Apply network policies for security isolation
kubectl apply -f network-policies/  # If available
```

### 3. Core Deployment
```bash
# Deploy Kuzuk cluster
./deploy.sh

# Monitor deployment progress
kubectl get pods -n kuzuk --watch

# Check logs for any issues
kubectl logs -f deployment/kuzuk -n kuzuk
```

### 4. Post-Deployment Verification

#### Health Checks
```bash
# Verify all pods are running
kubectl get pods -n kuzuk

# Check service endpoints
kubectl get endpoints -n kuzuk

# Test API connectivity
curl -f http://kuzuk.local/health

# Verify replication status
curl -f http://kuzuk.local/cluster/status
```

#### Monitoring Setup
```bash
# Access Grafana (default: admin/admin)
open http://grafana.kuzuk.local

# Import additional dashboards if needed
# Check Prometheus targets
open http://prometheus.kuzuk.local/targets
```

## Production Hardening

### 1. Security Hardening

#### RBAC Configuration
- Review and minimize service account permissions
- Implement pod security policies
- Enable network policies for micro-segmentation

#### Secret Management
```bash
# Use external secret management (recommended)
# Examples: HashiCorp Vault, AWS Secrets Manager, Azure Key Vault

# Rotate secrets regularly
kubectl create secret generic kuzuk-secrets-new \
  --from-literal=db-password=$(openssl rand -base64 32) \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2. Backup Strategy

#### Database Backups
```bash
# Set up automated database backups
kubectl create cronjob kuzu-backup \
  --image=kuzu-backup:latest \
  --schedule="0 2 * * *" \  # Daily at 2 AM
  --restart=OnFailure
```

#### Configuration Backups
```bash
# Backup all configurations
kubectl get all,configmap,secret -n kuzuk -o yaml > kuzuk-backup.yaml
```

### 3. Monitoring and Alerting

#### Prometheus Alerts
```bash
# Configure critical alerts
kubectl apply -f monitoring/alert-rules.yaml

# Set up alert routing
kubectl apply -f monitoring/alertmanager-config.yaml
```

#### Log Aggregation
```bash
# Deploy log collection (ELK, Fluentd, etc.)
kubectl apply -f logging/fluentd-daemonset.yaml
```

### 4. Performance Optimization

#### Resource Tuning
```bash
# Monitor resource usage
kubectl top pods -n kuzuk

# Adjust resource requests/limits based on usage
kubectl patch deployment kuzuk -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk","resources":{"requests":{"cpu":"2","memory":"4Gi"},"limits":{"cpu":"4","memory":"8Gi"}}}]}}}}'
```

#### Horizontal Pod Autoscaling
```bash
# Verify HPA is working
kubectl get hpa -n kuzuk

# Monitor scaling events
kubectl describe hpa kuzuk-hpa -n kuzuk
```

## Disaster Recovery

### 1. Multi-Region Setup
- Deploy replicas across multiple availability zones
- Configure cross-region replication for critical data
- Implement automated failover procedures

### 2. Backup and Restore Procedures
```bash
# Create disaster recovery runbook
# Test restore procedures regularly
# Document RTO/RPO requirements
```

### 3. Failover Testing
```bash
# Regular chaos engineering tests
kubectl delete pod -l app=kuzuk -n kuzuk  # Pod failure test
kubectl cordon <node-name>  # Node failure simulation
```

## Maintenance

### 1. Rolling Updates
```bash
# Update application image
kubectl set image deployment/kuzuk kuzuk=kuzuk:v2.0 -n kuzuk

# Monitor rollout
kubectl rollout status deployment/kuzuk -n kuzuk

# Rollback if needed
kubectl rollout undo deployment/kuzuk -n kuzuk
```

### 2. Scale Operations
```bash
# Scale replicas
kubectl scale deployment kuzuk --replicas=5 -n kuzuk

# Scale storage (if supported by storage class)
kubectl patch pvc kuzuk-data-pvc -n kuzuk -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'
```

### 3. Health Monitoring
```bash
# Regular health checks
./scripts/health-check.sh

# Performance baseline monitoring
./scripts/performance-benchmark.sh
```

## Troubleshooting

### Common Issues

#### Pod Startup Issues
```bash
# Check pod events
kubectl describe pod <pod-name> -n kuzuk

# Check logs
kubectl logs <pod-name> -n kuzuk

# Check resource constraints
kubectl top pods -n kuzuk
```

#### Networking Issues
```bash
# Test service connectivity
kubectl exec -it <pod-name> -n kuzuk -- curl http://kuzuk-service:8000/health

# Check ingress configuration
kubectl describe ingress kuzuk-ingress -n kuzuk

# Verify DNS resolution
kubectl exec -it <pod-name> -n kuzuk -- nslookup kuzuk-service
```

#### Storage Issues
```bash
# Check PVC status
kubectl get pvc -n kuzuk

# Check storage class
kubectl describe storageclass

# Check volume mounts
kubectl describe pod <pod-name> -n kuzuk
```

#### Performance Issues
```bash
# Check resource utilization
kubectl top pods -n kuzuk
kubectl top nodes

# Review metrics in Grafana
# Check for memory leaks or CPU bottlenecks
# Analyze query performance
```

## Support and Documentation

### Internal Documentation
- Maintain runbooks for common operations
- Document custom configurations
- Keep deployment procedures updated

### Monitoring and Observability
- Set up comprehensive dashboards
- Configure appropriate alerting
- Implement distributed tracing if needed

### Team Training
- Ensure team familiarity with kubectl commands
- Regular disaster recovery drills
- Knowledge sharing sessions

## Clean Up

### Safe Removal
```bash
# Remove deployment safely
./undeploy.sh

# Verify cleanup
kubectl get all --all-namespaces | grep kuzu
```

## Next Steps

1. **Performance Optimization**: Tune based on production workload
2. **Security Audit**: Regular security assessments
3. **Capacity Planning**: Monitor growth and scale accordingly
4. **Automation**: Implement GitOps for configuration management
5. **Compliance**: Ensure regulatory compliance requirements are met

For additional support or questions, refer to the project documentation or contact the development team.