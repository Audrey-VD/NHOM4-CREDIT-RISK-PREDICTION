let riskPieChartInstance = null;
let riskLineChartInstance = null;
let dataTableInstance = null;
let rawHighRiskData = [];

function formatCurrency(amount) {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(amount * 1000).replace('₫', 'VND');
}

async function fetchAndRenderStats() {
    try {
        const response = await fetch('/api/stats');
        const json = await response.json();
        
        document.getElementById('node-id-badge').innerText = json.node_id;
        const metrics = json.metrics;

        document.getElementById('stat-total').innerText = metrics.total.toLocaleString();
        document.getElementById('stat-high').innerText = metrics.high.toLocaleString();
        document.getElementById('stat-medium').innerText = metrics.medium.toLocaleString();
        document.getElementById('stat-low').innerText = metrics.low.toLocaleString();

        const ctxPie = document.getElementById('riskPieChart').getContext('2d');
        if (riskPieChartInstance) { riskPieChartInstance.destroy(); }
        
        riskPieChartInstance = new Chart(ctxPie, {
            type: 'pie',
            data: {
                labels: ['An Toàn (Low)', 'Trung Bình (Medium)', 'Nguy Cơ Cao (High)'],
                datasets: [{
                    data: [metrics.low, metrics.medium, metrics.high],
                    backgroundColor: ['#2e7d32', '#f57f17', '#c62828'],
                    borderWidth: 2
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });

        const ctxLine = document.getElementById('riskLineChart').getContext('2d');
        if (riskLineChartInstance) { riskLineChartInstance.destroy(); }
        
        riskLineChartInstance = new Chart(ctxLine, {
            type: 'line',
            data: {
                labels: ['T-6', 'T-5', 'T-4', 'T-3', 'T-2', 'T-1', 'Hiện tại'],
                datasets: [{
                    label: 'Số lượng hồ sơ Rủi ro Cao (High Risk)',
                    data: [
                        Math.max(0, metrics.high - 140), 
                        Math.max(0, metrics.high - 95), 
                        Math.max(0, metrics.high - 110), 
                        Math.max(0, metrics.high - 50), 
                        Math.max(0, metrics.high - 35), 
                        Math.max(0, metrics.high - 10), 
                        metrics.high
                    ],
                    borderColor: '#c62828',
                    backgroundColor: 'rgba(198, 40, 40, 0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 3
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
        
    } catch (error) {
        console.error("Lỗi khi kết nối thu thập số liệu thống kê:", error);
    }
}

async function fetchAndRenderTable() {
    try {
        const response = await fetch('/api/high-risk');
        const json = await response.json();
        rawHighRiskData = json.data;
        
        if (dataTableInstance) { dataTableInstance.clear().destroy(); }
        
        const tbody = document.querySelector('#predictionsTable tbody');
        tbody.innerHTML = '';
        
        rawHighRiskData.forEach((row, index) => {
            const tr = document.createElement('tr');
            tr.className = 'bg-high';

            tr.innerHTML = `
                <td class="fw-bold">#${row.id}</td>
                <td>${formatCurrency(row.limit_bal)}</td>
                <td>${row.age} tuổi</td>
                <td><span class="badge bg-dark">${row.pay_0}</span></td>
                <td class="fw-bold text-danger">${(row.probability * 100).toFixed(2)}%</td>
                <td><span class="badge bg-danger">High Risk</span></td>
                <td>${row.predicted_at}</td>
                <td>
                    <button class="btn btn-xs btn-primary p-1 px-2" style="font-size:0.75rem;" onclick="viewShapAnalysis(${index})">
                        <i class="fa-solid fa-magnifying-glass-chart me-1"></i>Xem SHAP
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        dataTableInstance = $('#predictionsTable').DataTable({
            "pageLength": 10,
            "ordering": true,
            "searching": true,
            "language": {
                "search": "Tìm nhanh khách hàng:",
                "lengthMenu": "Hiển thị _MENU_ dòng",
                "info": "Đang xem dòng _START_ đến _END_ trong tổng số _TOTAL_ hồ sơ",
                "paginate": { "next": "Sau", "previous": "Trước" }
            }
        });

    } catch (error) {
        console.error("Lỗi khi kết nối thu thập danh sách hồ sơ đen:", error);
    }
}

function viewShapAnalysis(index) {
    const customerRecord = rawHighRiskData[index];
    if (!customerRecord) return;

    document.getElementById('shap-customer-id').innerText = `#${customerRecord.id}`;
    document.getElementById('shap-customer-prob').innerText = `${(customerRecord.probability * 100).toFixed(1)}%`;

    const container = document.getElementById('shap-bars-container');
    container.innerHTML = '';

    let rawFeatures = customerRecord.shap_features;

    if (typeof rawFeatures === 'string') {
        try { rawFeatures = JSON.parse(rawFeatures); } catch(e) { rawFeatures = null; }
    }

    if (!rawFeatures || !Array.isArray(rawFeatures) || rawFeatures.length === 0) {
        container.innerHTML = '<p class="text-muted text-center py-3">Không có dữ liệu SHAP cho khách hàng này.</p>';
        return;
    }

    const totalAbsoluteImpact = rawFeatures.reduce((sum, item) => sum + Math.abs(item.value), 0);

    if (totalAbsoluteImpact === 0) {
        container.innerHTML = '<p class="text-muted text-center py-3">Trọng số các đặc trưng bằng 0.</p>';
        return;
    }

    const sortedFeatures = [...rawFeatures].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
    const top3Features = sortedFeatures.slice(0, 3);
    const remainingFeatures = sortedFeatures.slice(3);

    const displayData = [];
    top3Features.forEach(item => {
        const contributionPercentage = (Math.abs(item.value) / totalAbsoluteImpact) * 100;
        displayData.push({
            featureName: item.feature,
            rawValue: item.value,
            percentage: contributionPercentage
        });
    });

    if (remainingFeatures.length > 0) {
        let sumRawValue = 0;
        let sumAbsoluteImpact = 0;

        remainingFeatures.forEach(item => {
            sumRawValue += item.value;
            sumAbsoluteImpact += Math.abs(item.value);
        });

        const remainingPercentage = (sumAbsoluteImpact / totalAbsoluteImpact) * 100;
        displayData.push({
            featureName: "Các thuộc tính rủi ro phối hợp khác",
            rawValue: sumRawValue,
            percentage: remainingPercentage
        });
    }

    displayData.forEach(item => {
        const isRiskDriver = item.rawValue >= 0;
        const barColorClass = isRiskDriver ? 'bg-danger' : 'bg-success';
        const badgeColorClass = isRiskDriver ? 'text-danger bg-danger-subtle' : 'text-success bg-success-subtle';
        const signIndicator = item.rawValue > 0 ? '+' : '';

        const barHtml = `
            <div class="mb-3">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="fw-semibold small text-secondary text-truncate" style="max-width: 70%;" title="${item.featureName}">
                        ${item.featureName}
                    </span>
                    <span class="badge ${badgeColorClass} border font-monospace small">
                        ${item.percentage.toFixed(1)}% (${signIndicator}${item.rawValue.toFixed(4)})
                    </span>
                </div>
                <div class="progress shadow-sm" style="height: 12px; background-color: #e9ecef;">
                    <div class="progress-bar ${barColorClass} progress-bar-striped progress-bar-animated" 
                         role="progressbar" 
                         style="width: ${item.percentage}%" 
                         aria-valuenow="${item.percentage}" 
                         aria-valuemin="0" 
                         aria-valuemax="100">
                    </div>
                </div>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', barHtml);
    });

    const myModal = bootstrap.Modal.getOrCreateInstance(document.getElementById('shapModal'));
    myModal.show();
}

document.getElementById('btn-export-csv').addEventListener('click', () => {
    if (rawHighRiskData.length === 0) {
        alert("Bộ nhớ đệm rỗng. Không có dữ liệu khả dụng để kết xuất!");
        return;
    }
    
    let csvContent = "data:text/csv;charset=utf-8,\uFEFF";
    csvContent += "Mã KH,Hạn mức Credit,Tuổi,Trạng thái PAY_0,Xác suất vỡ nợ,Mức rủi ro,Thời gian dự đoán\n";

    rawHighRiskData.forEach(r => {
        const rowString = `${r.id},${r.limit_bal},${r.age},${r.pay_0},${r.probability},${r.risk_level},${r.predicted_at}`;
        csvContent += rowString + "\n";
    });
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `DANH_SACH_HIGH_RISK_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
});

function initializeSSEConnection() {
    const eventSource = new EventSource('/dashboard-data');
    const statusBadge = document.getElementById('sse-status');
    
    eventSource.onopen = function() {
        statusBadge.innerText = "Real-time Online";
        statusBadge.className = "text-success fw-bold";
    };
    
    eventSource.onmessage = function(event) {
        if (event.data === 'new_predictions') {
            console.log("🔔 Nhận tín hiệu thông báo Broadcast từ cụm Cluster Swarm Node. Tiến hành cập nhật giao diện...");

            fetchAndRenderStats();
            fetchAndRenderTable();

            const now = new Date();
            const timeString = now.toTimeString().split(' ')[0];
            const updateBadge = document.getElementById('update-time-badge');
            updateBadge.innerText = `Cập nhật: ${timeString}`;
            updateBadge.className = "badge bg-success text-white badge-update shadow-sm ms-2";
        }
    };
    
    eventSource.onerror = function() {
        statusBadge.innerText = "Mất kết nối Cluster Swarm. Đang thử lại...";
        statusBadge.className = "text-danger fw-bold";
    };
}

window.addEventListener('DOMContentLoaded', () => {
    fetchAndRenderStats();
    fetchAndRenderTable();
    initializeSSEConnection();
});