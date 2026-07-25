const fs = require('fs');
const path = require('path');

const baseDir = 'C:\\\\Users\\\\USER\\\\Desktop\\Projects\\Synthetic Indices Bot\\external\\mitemshub-indices\\src\\components\\intelligence';

const files = [
  'AINarrativePanel.tsx',
  'AlternativeScenarioPanel.tsx',
  'ConfidenceBreakdownPanel.tsx',
  'ConfidenceTrendPanel.tsx',
  'DecisionHistoryPanel.tsx',
  'EvidencePanel.tsx',
  'MarketIntelligencePanel.tsx',
  'MarketThesisPanel.tsx',
  'MultiTimeframePanel.tsx',
  'PostTradeLearningPanel.tsx',
  'RiskAssessmentPanel.tsx',
  'ThesisInvalidationPanel.tsx',
  'TradePlanPanel.tsx',
  'TradeProgressPanel.tsx',
  'MinimalTest.tsx',
  'TestPanel.tsx'
];

for (const file of files) {
  const filePath = path.join('C:\\\\Users\\\\USER\\\\Desktop\\Projects\\Synthetic Indices Bot\\external\\mitemshub-indices\\src\\components\\intelligence', file);
  if (!fs.existsSync(filePath)) {
    console.log('Skipping (not found): ' + file);
    continue;
  }
  
  let content = fs.readFileSync(filePath, 'utf8');
  
  // Ensure "use client" is at the very top
  if (!content.startsWith('"use client"')) {
    content = content.replace(/^"use client"[\r\n]*/, '');
    content = '"use client"\n\n' + content;
  }
  
  // Ensure React import is present
  if (!content.includes('import React from "react"')) {
    content = content.replace(/^"use client"\n/, '"use client"\n\nimport React from "react";\n');
  }
  
  // Fix line endings
  content = content.replace(/\r\n/g, '\n');
  
  fs.writeFileSync(filePath, content, 'utf8');
  console.log('Fixed: ' + file);
}

console.log('Done!');