#!/bin/bash

# KuzuScale Performance Benchmark Script
# This script runs performance tests against a deployed KuzuScale cluster

set -e

NAMESPACE="${KUZU_NAMESPACE:-kuzu-scale}"
DURATION="${BENCHMARK_DURATION:-60}"
CONCURRENCY="${BENCHMARK_CONCURRENCY:-10}"
OUTPUT_DIR="${BENCHMARK_OUTPUT_DIR:-./benchmark-results}"

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

# Check prerequisites
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
    
    # Create output directory
    mkdir -p "$OUTPUT_DIR"
    
    log_success "Prerequisites check passed"
}

# Get KuzuScale service URL
get_service_url() {
    local service_name="kuzu-scale-service"
    local port="8000"
    
    # Try to get service endpoint
    local service_ip
    service_ip=$(kubectl get service "$service_name" -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [ -z "$service_ip" ]; then
        # Try cluster IP
        service_ip=$(kubectl get service "$service_name" -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
    fi
    
    if [ -z "$service_ip" ]; then
        log_error "Could not determine service IP for $service_name"
        return 1
    fi
    
    echo "http://$service_ip:$port"
}

# Port-forward to service
setup_port_forward() {
    local kuzu_pod
    kuzu_pod=$(kubectl get pods -n "$NAMESPACE" -l app=kuzu-scale -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    
    if [ -z "$kuzu_pod" ]; then
        log_error "Could not find KuzuScale pod"
        return 1
    fi
    
    log_info "Setting up port-forward to $kuzu_pod..."
    kubectl port-forward "pod/$kuzu_pod" -n "$NAMESPACE" 8080:8000 &
    local pf_pid=$!
    
    # Wait for port-forward to establish
    sleep 3
    
    # Verify port-forward is working
    if curl -f -s --max-time 5 "http://localhost:8080/health" > /dev/null 2>&1; then
        log_success "Port-forward established successfully"
        echo $pf_pid
        return 0
    else
        log_error "Port-forward failed to establish"
        kill $pf_pid 2>/dev/null || true
        return 1
    fi
}

# Basic connectivity test
test_connectivity() {
    log_info "Testing basic connectivity..."
    
    local base_url="http://localhost:8080"
    local start_time=$(date +%s.%N)
    
    # Test health endpoint
    if curl -f -s --max-time 10 "$base_url/health" > /dev/null; then
        local end_time=$(date +%s.%N)
        local response_time=$(echo "$end_time - $start_time" | bc -l)
        log_success "Health endpoint responding (${response_time}s)"
    else
        log_error "Health endpoint not responding"
        return 1
    fi
    
    # Test cluster status endpoint
    if curl -f -s --max-time 10 "$base_url/cluster/status" > /dev/null; then
        log_success "Cluster status endpoint responding"
    else
        log_warning "Cluster status endpoint not responding"
    fi
    
    return 0
}

# Run basic query performance test
test_query_performance() {
    log_info "Running query performance test..."
    
    local base_url="http://localhost:8080"
    local output_file="$OUTPUT_DIR/query_performance.json"
    local temp_file="/tmp/query_test.txt"
    
    # Simple test queries
    local queries=(
        '{"query": "RETURN 1 as test"}'
        '{"query": "RETURN \"hello world\" as message"}'
        '{"query": "RETURN {name: \"test\", value: 42} as record"}'
    )
    
    echo "[]" > "$output_file"
    
    for i in "${!queries[@]}"; do
        local query="${queries[$i]}"
        log_info "Testing query $((i+1))/${#queries[@]}..."
        
        # Run multiple iterations of each query
        for iteration in {1..5}; do
            local start_time=$(date +%s.%N)
            
            local response
            local http_code
            response=$(curl -w "\n%{http_code}" -s -X POST \
                -H "Content-Type: application/json" \
                -d "$query" \
                --max-time 10 \
                "$base_url/query" 2>/dev/null || echo -e "\nERROR")
            
            local end_time=$(date +%s.%N)
            local response_time=$(echo "$end_time - $start_time" | bc -l)
            
            # Extract HTTP code
            http_code=$(echo "$response" | tail -n1)
            response=$(echo "$response" | head -n -1)
            
            # Create result record
            local result="{
                \"query_id\": $((i+1)),
                \"iteration\": $iteration,
                \"response_time\": $response_time,
                \"http_code\": \"$http_code\",
                \"success\": $([ "$http_code" = "200" ] && echo "true" || echo "false"),
                \"timestamp\": \"$(date -Iseconds)\"
            }"
            
            # Append to results
            jq ". += [$result]" "$output_file" > "$temp_file" && mv "$temp_file" "$output_file"
        done
    done
    
    # Calculate statistics
    local avg_response_time
    avg_response_time=$(jq -r '[.[] | select(.success == true) | .response_time] | add / length' "$output_file")
    
    local success_rate
    success_rate=$(jq -r '[.[] | select(.success == true)] | length as $success | ($success / (. | length) * 100)' "$output_file")
    
    log_success "Query performance test completed"
    log_info "Average response time: ${avg_response_time}s"
    log_info "Success rate: ${success_rate}%"
    
    echo "$avg_response_time $success_rate"
}

# Run concurrent load test
test_concurrent_load() {
    log_info "Running concurrent load test (duration: ${DURATION}s, concurrency: $CONCURRENCY)..."
    
    local base_url="http://localhost:8080"
    local output_file="$OUTPUT_DIR/load_test.json"
    
    # Check if hey tool is available (HTTP load testing tool)
    if command -v hey &> /dev/null; then
        log_info "Using 'hey' for load testing..."
        
        hey -z "${DURATION}s" -c "$CONCURRENCY" -m POST \
            -H "Content-Type: application/json" \
            -d '{"query": "RETURN 1 as load_test"}' \
            -o json \
            "$base_url/query" > "$output_file" 2>/dev/null || {
            log_warning "Hey load test failed, falling back to curl-based test"
            test_curl_load_test
        }
    else
        log_warning "'hey' tool not found, using curl-based load test"
        test_curl_load_test
    fi
}

# Fallback curl-based load test
test_curl_load_test() {
    local base_url="http://localhost:8080"
    local output_file="$OUTPUT_DIR/curl_load_test.txt"
    local pids=()
    
    log_info "Starting $CONCURRENCY concurrent workers for ${DURATION}s..."
    
    # Start concurrent workers
    for i in $(seq 1 "$CONCURRENCY"); do
        (
            local worker_file="$OUTPUT_DIR/worker_$i.txt"
            local count=0
            local start_time=$(date +%s)
            local end_time=$((start_time + DURATION))
            
            while [ $(date +%s) -lt $end_time ]; do
                local request_start=$(date +%s.%N)
                
                if curl -f -s -X POST \
                    -H "Content-Type: application/json" \
                    -d '{"query": "RETURN 1 as load_test"}' \
                    --max-time 5 \
                    "$base_url/query" > /dev/null 2>&1; then
                    local request_end=$(date +%s.%N)
                    local request_time=$(echo "$request_end - $request_start" | bc -l)
                    echo "SUCCESS,$request_time" >> "$worker_file"
                else
                    echo "FAILURE,0" >> "$worker_file"
                fi
                
                count=$((count + 1))
            done
            
            echo "Worker $i completed $count requests" >> "$output_file"
        ) &
        pids+=($!)
    done
    
    # Wait for all workers to complete
    for pid in "${pids[@]}"; do
        wait "$pid"
    done
    
    # Aggregate results
    local total_requests=0
    local successful_requests=0
    local total_time=0
    
    for i in $(seq 1 "$CONCURRENCY"); do
        local worker_file="$OUTPUT_DIR/worker_$i.txt"
        if [ -f "$worker_file" ]; then
            while IFS=',' read -r status time; do
                total_requests=$((total_requests + 1))
                if [ "$status" = "SUCCESS" ]; then
                    successful_requests=$((successful_requests + 1))
                    total_time=$(echo "$total_time + $time" | bc -l)
                fi
            done < "$worker_file"
            rm "$worker_file"
        fi
    done
    
    if [ $total_requests -gt 0 ]; then
        local success_rate=$((successful_requests * 100 / total_requests))
        local avg_response_time=$(echo "scale=6; $total_time / $successful_requests" | bc -l)
        local qps=$(echo "scale=2; $successful_requests / $DURATION" | bc -l)
        
        log_success "Load test completed"
        log_info "Total requests: $total_requests"
        log_info "Successful requests: $successful_requests"
        log_info "Success rate: ${success_rate}%"
        log_info "Average response time: ${avg_response_time}s"
        log_info "Queries per second: $qps"
    else
        log_error "No requests completed successfully"
    fi
}

# Test failover scenario
test_failover() {
    log_info "Testing failover scenario..."
    
    # Get current number of replicas
    local deployment="kuzu-scale"
    local current_replicas
    current_replicas=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
    
    if [ "$current_replicas" -le 1 ]; then
        log_warning "Skipping failover test - only 1 replica available"
        return 0
    fi
    
    log_info "Current replicas: $current_replicas"
    
    # Scale down by 1 replica
    local target_replicas=$((current_replicas - 1))
    log_info "Scaling down to $target_replicas replicas..."
    
    kubectl scale deployment "$deployment" --replicas="$target_replicas" -n "$NAMESPACE"
    
    # Wait for scaling to complete
    log_info "Waiting for scaling to complete..."
    kubectl wait --for=condition=available --timeout=60s deployment/"$deployment" -n "$NAMESPACE"
    
    # Test connectivity after scaling
    sleep 5
    if curl -f -s --max-time 10 "http://localhost:8080/health" > /dev/null; then
        log_success "Service available after scaling down"
    else
        log_error "Service not available after scaling down"
    fi
    
    # Scale back up
    log_info "Scaling back up to $current_replicas replicas..."
    kubectl scale deployment "$deployment" --replicas="$current_replicas" -n "$NAMESPACE"
    kubectl wait --for=condition=available --timeout=60s deployment/"$deployment" -n "$NAMESPACE"
    
    # Test connectivity after scaling back up
    sleep 5
    if curl -f -s --max-time 10 "http://localhost:8080/health" > /dev/null; then
        log_success "Service available after scaling back up"
    else
        log_error "Service not available after scaling back up"
    fi
    
    log_success "Failover test completed"
}

# Generate performance report
generate_performance_report() {
    local report_file="$OUTPUT_DIR/performance_report.txt"
    
    echo "=====================================" > "$report_file"
    echo "    KUZUSCALE PERFORMANCE REPORT     " >> "$report_file"
    echo "=====================================" >> "$report_file"
    echo "Timestamp: $(date)" >> "$report_file"
    echo "Namespace: $NAMESPACE" >> "$report_file"
    echo "Duration: ${DURATION}s" >> "$report_file"
    echo "Concurrency: $CONCURRENCY" >> "$report_file"
    echo "" >> "$report_file"
    
    # Query performance summary
    if [ -f "$OUTPUT_DIR/query_performance.json" ]; then
        echo "QUERY PERFORMANCE:" >> "$report_file"
        echo "==================" >> "$report_file"
        
        local avg_time
        avg_time=$(jq -r '[.[] | select(.success == true) | .response_time] | add / length' "$OUTPUT_DIR/query_performance.json")
        local success_rate
        success_rate=$(jq -r '[.[] | select(.success == true)] | length as $success | ($success / (. | length) * 100)' "$OUTPUT_DIR/query_performance.json")
        
        echo "Average Response Time: ${avg_time}s" >> "$report_file"
        echo "Success Rate: ${success_rate}%" >> "$report_file"
        echo "" >> "$report_file"
    fi
    
    # Load test summary
    if [ -f "$OUTPUT_DIR/load_test.json" ]; then
        echo "LOAD TEST RESULTS:" >> "$report_file"
        echo "==================" >> "$report_file"
        
        # Parse hey output if available
        local total_requests
        total_requests=$(jq -r '.summary.total' "$OUTPUT_DIR/load_test.json" 2>/dev/null || echo "N/A")
        local qps
        qps=$(jq -r '.summary.rps' "$OUTPUT_DIR/load_test.json" 2>/dev/null || echo "N/A")
        local avg_latency
        avg_latency=$(jq -r '.summary.average' "$OUTPUT_DIR/load_test.json" 2>/dev/null || echo "N/A")
        
        echo "Total Requests: $total_requests" >> "$report_file"
        echo "Queries per Second: $qps" >> "$report_file"
        echo "Average Latency: $avg_latency" >> "$report_file"
        echo "" >> "$report_file"
    fi
    
    # Resource usage
    echo "RESOURCE USAGE:" >> "$report_file"
    echo "===============" >> "$report_file"
    kubectl top pods -n "$NAMESPACE" 2>/dev/null >> "$report_file" || echo "Resource metrics not available" >> "$report_file"
    echo "" >> "$report_file"
    
    # Pod status
    echo "POD STATUS:" >> "$report_file"
    echo "===========" >> "$report_file"
    kubectl get pods -n "$NAMESPACE" -o wide >> "$report_file"
    echo "" >> "$report_file"
    
    log_success "Performance report generated: $report_file"
    
    # Display summary
    echo ""
    echo "📊 PERFORMANCE SUMMARY"
    echo "======================"
    cat "$report_file"
}

# Clean up function
cleanup() {
    if [ -n "$PF_PID" ]; then
        log_info "Cleaning up port-forward..."
        kill "$PF_PID" 2>/dev/null || true
        wait "$PF_PID" 2>/dev/null || true
    fi
}

# Set up cleanup trap
trap cleanup EXIT

# Main execution
main() {
    echo "🚀 KuzuScale Performance Benchmark Starting..."
    echo "Namespace: $NAMESPACE"
    echo "Duration: ${DURATION}s"
    echo "Concurrency: $CONCURRENCY"
    echo "Output Directory: $OUTPUT_DIR"
    echo ""
    
    check_prerequisites
    
    # Set up port-forward
    PF_PID=$(setup_port_forward)
    if [ $? -ne 0 ]; then
        log_error "Failed to set up port-forward"
        exit 1
    fi
    
    # Run tests
    test_connectivity
    test_query_performance
    test_concurrent_load
    test_failover
    
    # Generate report
    generate_performance_report
    
    log_success "🎉 Performance benchmark completed successfully!"
}

# Handle script arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -c|--concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -n, --namespace NAME    Kubernetes namespace (default: kuzu-scale)"
            echo "  -d, --duration SECONDS  Test duration in seconds (default: 60)"
            echo "  -c, --concurrency NUM   Number of concurrent workers (default: 10)"
            echo "  -o, --output DIR        Output directory for results (default: ./benchmark-results)"
            echo "  -h, --help              Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  KUZU_NAMESPACE          Override default namespace"
            echo "  BENCHMARK_DURATION      Override default duration"
            echo "  BENCHMARK_CONCURRENCY   Override default concurrency"
            echo "  BENCHMARK_OUTPUT_DIR    Override default output directory"
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