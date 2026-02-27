const stages = [
  {
    name: '1) PDF parse',
    summary: 'IRONCLAD reads text spans, layout blocks, and page coordinates from the source PDF.',
    outputs: ['Raw spans and block geometry', 'Candidate tables and figure anchors', 'Document metadata (title/pages/doc_id)'],
    sample: {
      doc_id: 'paper_demo_001',
      page_count: 12,
      parsed_blocks: 482,
      detected_tables: 3
    }
  },
  {
    name: '2) Property extraction',
    summary: 'Rule-driven extractors detect polymer/material properties with associated context.',
    outputs: ['Record candidates: material/property/value', 'Citation hints', 'Provenance snippet + page index'],
    sample: {
      material: 'PEO-LiTFSI',
      property: 'ionic_conductivity',
      value_min: 1.2e-4,
      unit_original: 'S/cm',
      provenance: { page: 5, snippet: '...ionic conductivity reached 1.2×10^-4 S/cm at 25°C...' }
    }
  },
  {
    name: '3) Normalization + checks',
    summary: 'Units are normalized when possible and constraints are evaluated for consistency.',
    outputs: ['Original and SI values', 'Hard fail / soft warning lists', 'Confidence and method tags'],
    sample: {
      value_min: 1.2e-4,
      unit_original: 'S/cm',
      value_si_min: 0.012,
      unit_si: 'S/m',
      constraints: { hard_fail: [], soft_warn: ['temperature not explicit in same sentence'] }
    }
  },
  {
    name: '4) Origin + comparison',
    summary: 'Records are labeled as this_work/literature/mixed/unclear and aggregated into comparison rows.',
    outputs: ['Origin label per record', 'This work vs cited literature rollups', 'Novelty flags with optional external baseline'],
    sample: {
      material: 'PEO-LiTFSI',
      property: 'ionic_conductivity',
      this_work: '1.2e-4 S/cm',
      paper_cited_literature: '3.0e-5 to 9.0e-5 S/cm',
      external_baseline: '1.0e-5 to 8.0e-5 S/cm',
      novelty_flag: 'possible_outlier_high'
    }
  },
  {
    name: '5) Browser exploration',
    summary: 'The GitHub Pages viewer provides filtering, table/figure browsing, and export without a backend.',
    outputs: ['Interactive records grid', 'Comparison/tables/figures/logs tabs', 'Download filtered CSV/JSON for analysis'],
    sample: {
      viewer_actions: ['search: "conductivity"', 'origin: this_work', 'hard_fail_only: false'],
      exported_file: 'ironclad_filtered.csv'
    }
  }
];

const stepsEl = document.getElementById('workflowSteps');
const titleEl = document.getElementById('stageTitle');
const summaryEl = document.getElementById('stageSummary');
const outputsEl = document.getElementById('stageOutputs');
const jsonEl = document.getElementById('stageJson');

function renderStage(i){
  const s = stages[i];
  titleEl.textContent = s.name;
  summaryEl.textContent = s.summary;
  outputsEl.innerHTML = '';
  s.outputs.forEach((line) => {
    const li = document.createElement('li');
    li.textContent = line;
    outputsEl.appendChild(li);
  });
  jsonEl.textContent = JSON.stringify(s.sample, null, 2);

  document.querySelectorAll('.workflow-step').forEach((btn, idx) => {
    btn.classList.toggle('active', idx === i);
  });
}

stages.forEach((s, i) => {
  const btn = document.createElement('button');
  btn.className = 'workflow-step';
  btn.type = 'button';
  btn.textContent = s.name;
  btn.addEventListener('click', () => renderStage(i));
  stepsEl.appendChild(btn);
});

renderStage(0);
