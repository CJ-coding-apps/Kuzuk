#!/bin/bash

# KuzuScale Production Health Check Script
# This script performs comprehensive health checks on a deployed KuzuScale cluster

set -e

NAMESPACE="${KUZU_NAMESPACE:-kuzu-scale}"
TIMEOUT="${HEALTH_CHECK_TIMEOUT:-30}"
RETRIES="${HEALTH_CHECK_RETRIES:-3}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Health check tracking
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

check_result() {
    local name="$1"
    local status="$2"
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    if [ "$status" = "0" ]; then
        log_success "$name"
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        log_error "$name"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    fi
}

# Check if kubectl is available and cluster is accessible
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log_error "Namespace '$NAMESPACE' does not exist"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Check pod status
check_pod_status() {
    log_info "Checking pod status..."
    
    local pods
    pods=$(kubectl get pods -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')
    
    if [ -z "$pods" ]; then
        check_result "Pod existence check" 1
        return 1
    fi
    
    for pod in $pods; do
        local status
        status=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
        
        if [ "$status" = "Running" ]; then
            # Check if all containers are ready
            local ready
            ready=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
            
            if [ "$ready" = "True" ]; then
                check_result "Pod $pod status" 0
            else
                check_result "Pod $pod readiness" 1
                
                # Show container status for debugging
                log_warning "Container status for $pod:"
                kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[*].state}' | jq '.' 2>/dev/null || echo "Raw: $(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[*].state}')"
            fi
        else
            check_result "Pod $pod status (expected: Running, got: $status)" 1
        fi
    done
}

# Check service endpoints
check_service_endpoints() {
    log_info "Checking service endpoints..."
    
    local services
    services=$(kubectl get services -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')
    
    for service in $services; do
        local endpoints
        endpoints=$(kubectl get endpoints "$service" -n "$NAMESPACE" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)
        
        if [ -n "$endpoints" ]; then
            check_result "Service $service endpoints" 0
        else
            check_result "Service $service endpoints (no endpoints found)" 1
        fi
    done
}

# Check persistent volume claims
check_pvc_status() {
    log_info "Checking persistent volume claims..."
    
    local pvcs
    pvcs=$(kubectl get pvc -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$pvcs" ]; then
        log_warning "No PVCs found in namespace $NAMESPACE"
        return 0
    fi
    
    for pvc in $pvcs; do
        local status
        status=$(kubectl get pvc "$pvc" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
        
        if [ "$status" = "Bound" ]; then
            check_result "PVC $pvc status" 0
        else
            check_result "PVC $pvc status (expected: Bound, got: $status)" 1
        fi
    done
}

# Check ingress status
check_ingress_status() {
    log_info "Checking ingress status..."
    
    local ingresses
    ingresses=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$ingresses" ]; then
        log_warning "No ingresses found in namespace $NAMESPACE"
        return 0
    fi
    
    for ingress in $ingresses; do
        local hosts
        hosts=$(kubectl get ingress "$ingress" -n "$NAMESPACE" -o jsonpath='{.spec.rules[*].host}')
        
        for host in $hosts; do
            if [ -n "$host" ]; then
                check_result "Ingress $ingress host configuration ($host)" 0
            else
                check_result "Ingress $ingress host configuration" 1
            fi
        done
    done
}

# Check application health endpoints
check_application_health() {
    log_info "Checking application health endpoints..."
    
    # Port-forward to check health endpoint
    local kuzu_pod
    kuzu_pod=$(kubectl get pods -n "$NAMESPACE" -l app=kuzu-scale -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$kuzu_pod" ]; then
        check_result "KuzuScale pod discovery" 1
        return 1
    fi
    
    # Check if the pod is ready before port-forwarding
    local ready
    ready=$(kubectl get pod "$kuzu_pod" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
    
    if [ "$ready" != "True" ]; then
        check_result "KuzuScale pod readiness (required for health check)" 1
        return 1
    fi
    
    # Port-forward with timeout and background process
    log_info "Starting port-forward to check health endpoint..."
    kubectl port-forward "pod/$kuzu_pod" -n "$NAMESPACE" 8080:8000 &
    local pf_pid=$!
    
    # Wait a moment for port-forward to establish
    sleep 2
    
    # Check health endpoint with retries
    local attempt=1
    local health_check_passed=false
    
    while [ $attempt -le $RETRIES ]; do
        if curl -f -s --max-time "$TIMEOUT" "http://localhost:8080/health" > /dev/null 2>&1; then
            health_check_passed=true
            break
        fi
        
        log_warning "Health check attempt $attempt failed, retrying..."
        attempt=$((attempt + 1))
        sleep 1
    done
    
    # Clean up port-forward
    kill $pf_pid 2>/dev/null || true
    wait $pf_pid 2>/dev/null || true
    
    if [ "$health_check_passed" = true ]; then
        check_result "Application health endpoint" 0
    else
        check_result "Application health endpoint (failed after $RETRIES attempts)" 1
    fi
}

# Check monitoring endpoints
check_monitoring_health() {
    log_info "Checking monitoring endpoints..."
    
    # Check Prometheus
    local prometheus_pod
    prometheus_pod=$(kubectl get pods -n "$NAMESPACE" -l app=prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -n "$prometheus_pod" ]; then
        local ready
        ready=$(kubectl get pod "$prometheus_pod" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
        
        if [ "$ready" = "True" ]; then
            check_result "Prometheus pod readiness" 0
            
            # Quick port-forward test for Prometheus
            kubectl port-forward "pod/$prometheus_pod" -n "$NAMESPACE" 9091:9090 &
            local pf_pid=$!
            sleep 2
            
            if curl -f -s --max-time 5 "http://localhost:9091/-/ready" > /dev/null 2>&1; then
                check_result "Prometheus health endpoint" 0
            else
                check_result "Prometheus health endpoint" 1
            fi
            
            kill $pf_pid 2>/dev/null || true
            wait $pf_pid 2>/dev/null || true
        else
            check_result "Prometheus pod readiness" 1
        fi
    else
        log_warning "Prometheus pod not found"
    fi
    
    # Check Grafana
    local grafana_pod
    grafana_pod=$(kubectl get pods -n "$NAMESPACE" -l app=grafana -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -n "$grafana_pod" ]; then
        local ready
        ready=$(kubectl get pod "$grafana_pod" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
        
        if [ "$ready" = "True" ]; then
            check_result "Grafana pod readiness" 0
            
            # Quick port-forward test for Grafana
            kubectl port-forward "pod/$grafana_pod" -n "$NAMESPACE" 3001:3000 &
            local pf_pid=$!
            sleep 2
            
            if curl -f -s --max-time 5 "http://localhost:3001/api/health" > /dev/null 2>&1; then
                check_result "Grafana health endpoint" 0
            else
                check_result "Grafana health endpoint" 1
            fi
            
            kill $pf_pid 2>/dev/null || true
            wait $pf_pid 2>/dev/null || true
        else
            check_result "Grafana pod readiness" 1
        fi
    else
        log_warning "Grafana pod not found"
    fi
}

# Check resource usage
check_resource_usage() {
    log_info "Checking resource usage..."
    
    # Check if metrics-server is available
    if ! kubectl top nodes &> /dev/null; then
        log_warning "Metrics server not available, skipping resource usage checks"
        return 0
    fi
    
    # Check node resource usage
    log_info "Node resource usage:"
    kubectl top nodes
    
    echo ""
    
    # Check pod resource usage
    log_info "Pod resource usage:"
    kubectl top pods -n "$NAMESPACE" 2>/dev/null || log_warning "Could not get pod metrics"
    
    check_result "Resource usage check" 0
}

# Check events for any warnings or errors
check_events() {
    log_info "Checking recent events..."
    
    local warning_events
    warning_events=$(kubectl get events -n "$NAMESPACE" --field-selector type=Warning --sort-by=.metadata.creationTimestamp 2>/dev/null | wc -l)
    
    local error_events
    error_events=$(kubectl get events -n "$NAMESPACE" --field-selector type=Error --sort-by=.metadata.creationTimestamp 2>/dev/null | wc -l)
    
    if [ "$warning_events" -gt 1 ] || [ "$error_events" -gt 1 ]; then
        log_warning "Found $warning_events warning events and $error_events error events"
        
        echo ""
        log_info "Recent warning events:"
        kubectl get events -n "$NAMESPACE" --field-selector type=Warning --sort-by=.metadata.creationTimestamp | tail -5
        
        echo ""
        log_info "Recent error events:"
        kubectl get events -n "$NAMESPACE" --field-selector type=Error --sort-by=.metadata.creationTimestamp | tail -5
        
        check_result "Event analysis (warnings/errors found)" 1
    else
        check_result "Event analysis" 0
    fi
}

# Generate health report
generate_report() {
    echo ""
    echo "================================="
    echo "       HEALTH CHECK REPORT       "
    echo "================================="
    echo "Namespace: $NAMESPACE"
    echo "Timestamp: $(date)"
    echo ""
    echo "Total Checks: $TOTAL_CHECKS"
    echo "Passed: $PASSED_CHECKS"
    echo "Failed: $FAILED_CHECKS"
    echo ""
    
    local success_rate=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))
    echo "Success Rate: $success_rate%"
    echo ""
    
    if [ $FAILED_CHECKS -eq 0 ]; then
        log_success "🎉 All health checks passed! Cluster is healthy."
        return 0
    elif [ $success_rate -ge 80 ]; then
        log_warning "⚠️  Some issues detected but cluster is mostly healthy ($success_rate% success rate)"
        return 1
    else
        log_error "🚨 Significant issues detected! Cluster needs attention ($success_rate% success rate)"
        return 2
    fi
}

# Main execution
main() {
    echo "🏥 KuzuScale Health Check Starting..."
    echo "Namespace: $NAMESPACE"
    echo "Timeout: ${TIMEOUT}s"
    echo "Retries: $RETRIES"
    echo ""
    
    check_prerequisites
    
    echo ""
    echo "🔍 Running health checks..."
    echo ""
    
    check_pod_status
    check_service_endpoints
    check_pvc_status
    check_ingress_status
    check_application_health
    check_monitoring_health
    check_resource_usage
    check_events
    
    return $(generate_report)
}

# Handle script arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -t|--timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        -r|--retries)
            RETRIES="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -n, --namespace NAME    Kubernetes namespace (default: kuzu-scale)"
            echo "  -t, --timeout SECONDS   Timeout for health checks (default: 30)"
            echo "  -r, --retries COUNT     Number of retries for failed checks (default: 3)"
            echo "  -h, --help              Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  KUZU_NAMESPACE          Override default namespace"
            echo "  HEALTH_CHECK_TIMEOUT    Override default timeout"
            echo "  HEALTH_CHECK_RETRIES    Override default retries"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            log_info "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Execute main function
main
exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    log_success "Health check completed successfully"
elif [ $exit_code -eq 1 ]; then
    log_warning "Health check completed with warnings"
else
    log_error "Health check completed with errors"
fi

exit $exit_code