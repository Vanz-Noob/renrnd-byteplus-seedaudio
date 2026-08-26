/* =====================================================================
   BytePlus Voice Chat - Performance Comparison Chart (ECharts IIFE)
   Membandingkan latensi pipeline v1.0 (sequential) vs v2.0 (parallel)
   ===================================================================== */
(function () {
  'use strict';

  function initLatencyChart() {
    var container = document.getElementById('latencyChart');
    if (!container || typeof echarts === 'undefined') {
      if (container && typeof echarts === 'undefined') {
        container.textContent = 'ECharts belum dimuat. Chart tidak dapat ditampilkan.';
      }
      return;
    }

    // Data latensi (dalam detik)
    var categories = [
      'Waktu STT',
      'AI Token Pertama',
      'Audio TTS Pertama',
      'Total hingga Audio Pertama'
    ];
    var v1Data = [5.0, 3.0, 2.0, 10.0];   // v1.0 sequential (detik)
    var v2Data = [0.6, 0.5, 1.0, 2.5];    // v2.0 parallel pipeline (detik)

    var chart = echarts.init(container, null, { renderer: 'canvas' });

    var option = {
      backgroundColor: 'transparent',
      color: ['#6C5CE7', '#00CEC9'],
      title: {
        text: 'Perbandingan Latensi Pipeline',
        subtext: 'v1.0 Sequential vs v2.0 Parallel (detik, makin rendah makin baik)',
        left: 'center',
        textStyle: {
          color: '#EAEAEA',
          fontFamily: 'Outfit, sans-serif',
          fontSize: 18,
          fontWeight: 700
        },
        subtextStyle: {
          color: '#8888AA',
          fontFamily: 'Outfit, sans-serif',
          fontSize: 12
        }
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: '#1A1A2E',
        borderColor: '#2A2A4A',
        textStyle: { color: '#EAEAEA', fontFamily: 'Outfit, sans-serif' },
        valueFormatter: function (val) {
          return val + ' detik';
        }
      },
      legend: {
        data: ['v1.0 Sequential', 'v2.0 Parallel'],
        top: 64,
        textStyle: { color: '#8888AA', fontFamily: 'Outfit, sans-serif' },
        itemWidth: 14,
        itemHeight: 14
      },
      grid: {
        left: '4%',
        right: '4%',
        bottom: '6%',
        top: 110,
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: {
          color: '#EAEAEA',
          fontFamily: 'Outfit, sans-serif',
          fontSize: 12,
          interval: 0,
          rotate: 0
        },
        axisLine: { lineStyle: { color: '#2A2A4A' } },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        name: 'Detik',
        nameTextStyle: { color: '#8888AA', fontFamily: 'Outfit, sans-serif' },
        axisLabel: {
          color: '#8888AA',
          fontFamily: 'JetBrainsMono, monospace',
          formatter: '{value}s'
        },
        splitLine: { lineStyle: { color: '#2A2A4A', type: 'dashed' } },
        axisLine: { show: false }
      },
      series: [
        {
          name: 'v1.0 Sequential',
          type: 'bar',
          barWidth: '28%',
          barGap: '15%',
          itemStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#6C5CE7' },
                { offset: 1, color: '#4A3DB0' }
              ]
            },
            borderRadius: [6, 6, 0, 0]
          },
          data: v1Data,
          label: {
            show: true,
            position: 'top',
            color: '#EAEAEA',
            fontFamily: 'JetBrainsMono, monospace',
            fontSize: 11,
            formatter: '{c}s'
          }
        },
        {
          name: 'v2.0 Parallel',
          type: 'bar',
          barWidth: '28%',
          itemStyle: {
            color: {
              type: 'linear',
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: '#00CEC9' },
                { offset: 1, color: '#008B89' }
              ]
            },
            borderRadius: [6, 6, 0, 0]
          },
          data: v2Data,
          label: {
            show: true,
            position: 'top',
            color: '#EAEAEA',
            fontFamily: 'JetBrainsMono, monospace',
            fontSize: 11,
            formatter: '{c}s'
          }
        }
      ]
    };

    chart.setOption(option);

    // Responsif: resize chart saat ukuran jendela berubah
    var resizeTimer = null;
    window.addEventListener('resize', function () {
      if (resizeTimer) { clearTimeout(resizeTimer); }
      resizeTimer = setTimeout(function () { chart.resize(); }, 150);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLatencyChart);
  } else {
    initLatencyChart();
  }
})();
