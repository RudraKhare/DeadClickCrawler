import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { GridLegacy } from '@mui/material';
import { Box, Button, Card, CardContent, CircularProgress, Container, TextField, Typography, Snackbar, Alert, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper, Tooltip, IconButton, Dialog, DialogTitle, DialogContent } from '@mui/material';
import { PieChart, Pie, Cell, Tooltip as ReTooltip, Legend, ResponsiveContainer } from 'recharts';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import './App.css';

const API_BASE = 'http://localhost:8000';

const STATUS_COLORS: Record<string, string> = {
  active_ui_change: '#4caf50',
  active_navigation: '#2196f3',
  active_title_change: '#00bcd4',
  dead_click: '#f44336',
  error: '#ff9800',
  element_not_found: '#9e9e9e',
  not_clickable: '#ffb300',
};

interface Summary {
  total_tested: number;
  active_percentage: number;
  dead_percentage: number;
  error_percentage: number;
  most_common_classes: [string, number][];
  click_status_breakdown: Record<string, number>;
}

interface ElementInfo {
  tag_name: string;
  text: string;
  class_names: string;
  id: string;
  xpath: string;
  css_selector: string;
}

interface TestResult {
  element_info: ElementInfo;
  click_status: string;
  error_message: string;
  url_before: string;
  url_after: string;
}

interface Results {
  summary: Summary;
  results: TestResult[];
  total_elements_found: number;
  elements_tested: number;
  active_clicks: number;
  dead_clicks: number;
  errors: number;
  url: string;
  timestamp: string;
}

const App: React.FC = () => {
  const [url, setUrl] = useState('https://cont-sites.bajajfinserv.in/personal-loan');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState('');
  const [snackbar, setSnackbar] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [waitTime, setWaitTime] = useState(5);
  const [strictness, setStrictness] = useState('normal');

  const fetchResults = async (customWaitTime?: number, customStrictness?: string) => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.get(`${API_BASE}/results`);
      setResults(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to fetch results');
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchResults();
  }, []);

  const handleRunTest = async () => {
    setLoading(true);
    setError('');
    setSnackbar('Test started. This may take a minute...');
    try {
      const res = await axios.post(`${API_BASE}/run-test`, null, { params: { url, wait_time: waitTime, strictness } });
      setSnackbar('Test completed!');
      if (res.data && res.data.report) {
        setResults(res.data.report);
      } else {
        await fetchResults();
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to run test');
    }
    setLoading(false);
  };

  const deadClicks = results?.results?.filter(r => r.click_status === 'dead_click' || r.click_status === 'element_not_found' || r.click_status === 'not_clickable') || [];

  const chartData = results && results.summary && results.summary.click_status_breakdown
    ? Object.entries(results.summary.click_status_breakdown).map(([status, count]) => ({
        name: status,
        value: count,
      }))
    : [];

  const isValidResults = results && results.summary && Array.isArray(results.results);

  return (
    <>
      <header className="app-header">
        <Typography className="app-title" variant="h3" align="center" gutterBottom>
          <span role="img" aria-label="web crawler" style={{marginRight: 8}}>🕸️</span> Web Crawler Dashboard
        </Typography>
        <Typography className="app-subtitle" align="center">
          Enterprise Clickability Analytics &amp; Dead Link Finder
        </Typography>
        <Tooltip title="How does this work?">
          <IconButton onClick={() => setHelpOpen(true)} size="large" sx={{ position: 'absolute', right: 32, top: 32 }}>
            <InfoOutlinedIcon fontSize="large" />
          </IconButton>
        </Tooltip>
      </header>
      <Container maxWidth="xl" sx={{ py: 4 }}>
        <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center', gap: 2 }}>
          <TextField
            label="Test URL"
            value={url}
            onChange={e => setUrl(e.target.value)}
            sx={{ width: 400 }}
          />
          <Button variant="contained" color="primary" onClick={handleRunTest} disabled={loading} sx={{ fontWeight: 600, fontSize: '1.1rem', borderRadius: 8, boxShadow: '0 2px 8px 0 rgba(80,120,255,0.08)' }}>
            {loading ? <CircularProgress size={24} /> : 'Run Test'}
          </Button>
        </Box>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {!isValidResults && !loading && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            No valid report data received from backend.<br/>
            Please check backend logs for errors, or try running the test again.<br/>
            <pre style={{ fontSize: 12, marginTop: 8, color: '#888', maxHeight: 200, overflow: 'auto' }}>{JSON.stringify(results, null, 2)}</pre>
          </Alert>
        )}
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
            <CircularProgress size={48} />
          </Box>
        )}
        {isValidResults && !loading && (
          <>
            <GridLegacy container spacing={3}>
              <GridLegacy item xs={12} md={3}>
                <Card className="glass-card">
                  <CardContent>
                    <div className="stats-label">Total Elements</div>
                    <div className="stats-value">{results.total_elements_found}</div>
                  </CardContent>
                </Card>
              </GridLegacy>
              <GridLegacy item xs={12} md={3}>
                <Card className="glass-card">
                  <CardContent>
                    <div className="stats-label">Active Clicks</div>
                    <div className="stats-value" style={{ color: '#4caf50' }}>{results.active_clicks}</div>
                    <div className="stats-percent">{results.summary ? results.summary.active_percentage : 0}%</div>
                  </CardContent>
                </Card>
              </GridLegacy>
              <GridLegacy item xs={12} md={3}>
                <Card className="glass-card">
                  <CardContent>
                    <div className="stats-label">Dead Clicks</div>
                    <div className="stats-value" style={{ color: '#f44336' }}>{results.dead_clicks}</div>
                    <div className="stats-percent">{results.summary ? results.summary.dead_percentage : 0}%</div>
                  </CardContent>
                </Card>
              </GridLegacy>
              <GridLegacy item xs={12} md={3}>
                <Card className="glass-card">
                  <CardContent>
                    <div className="stats-label">Errors</div>
                    <div className="stats-value" style={{ color: '#ff9800' }}>{results.errors}</div>
                    <div className="stats-percent">{results.summary ? results.summary.error_percentage : 0}%</div>
                  </CardContent>
                </Card>
              </GridLegacy>
            </GridLegacy>
            {results && results.total_elements_found === 0 && !loading && (
              <Box sx={{ mt: 6, textAlign: 'center' }}>
                <Typography variant="h5" color="text.secondary" gutterBottom>
                  No clickable elements found on this page.
                </Typography>
                <Typography variant="body1" color="text.secondary" sx={{ mb: 2 }}>
                  This can happen if the page loads elements slowly, uses unusual HTML, or is highly dynamic.<br/>
                  Try increasing the wait time or lowering detection strictness.
                </Typography>
                <Button variant="outlined" onClick={() => setShowOptions(true)} sx={{ mr: 2 }}>Detection Options</Button>
                <Button variant="contained" onClick={handleRunTest}>Retry</Button>
              </Box>
            )}
            <Box sx={{ my: 4, height: 350 }}>
              <Typography variant="h5" gutterBottom>Click Status Breakdown</Typography>
              {results && results.summary && results.summary.click_status_breakdown ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={chartData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={120}
                      label
                    >
                      {chartData.map((entry, idx) => (
                        <Cell key={`cell-${idx}`} fill={STATUS_COLORS[entry.name] || '#8884d8'} />
                      ))}
                    </Pie>
                    <ReTooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <Alert severity="warning">No click status breakdown available.</Alert>
              )}
            </Box>
            <Box sx={{ my: 4 }}>
              <Typography variant="h5" gutterBottom>Dead/Problematic Clicks</Typography>
              <TableContainer component={Paper} className="glass-card">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>#</TableCell>
                      <TableCell>Tag</TableCell>
                      <TableCell>Class</TableCell>
                      <TableCell>Text</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Error</TableCell>
                      <TableCell>Location (XPath)</TableCell>
                      <TableCell>Location (CSS)</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {deadClicks.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell>{i + 1}</TableCell>
                        <TableCell>{r.element_info.tag_name}</TableCell>
                        <TableCell>{r.element_info.class_names}</TableCell>
                        <TableCell>{r.element_info.text?.slice(0, 60)}</TableCell>
                        <TableCell style={{ color: STATUS_COLORS[r.click_status] || undefined }}>{r.click_status}</TableCell>
                        <TableCell>{r.error_message}</TableCell>
                        <TableCell>
                          <code style={{ fontSize: 12 }}>{r.element_info.xpath}</code>
                        </TableCell>
                        <TableCell>
                          <code style={{ fontSize: 12 }}>{r.element_info.css_selector}</code>
                        </TableCell>
                      </TableRow>
                    ))}
                    {deadClicks.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={8} align="center">No dead/problematic clicks found!</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                <b>Tip:</b> To find a dead click, use the XPath or CSS selector above in your browser's DevTools. Hover over the row for more info. Even non-developers can copy-paste these into the browser to locate the problematic element visually.
              </Typography>
            </Box>
          </>
        )}
        <Snackbar open={!!snackbar} autoHideDuration={4000} onClose={() => setSnackbar('')}>
          <Alert onClose={() => setSnackbar('')} severity="info" sx={{ width: '100%' }}>
            {snackbar}
          </Alert>
        </Snackbar>
      </Container>
      <footer className="app-footer">
        <span>© {new Date().getFullYear()} Web Crawler Enterprise. All rights reserved.</span>
      </footer>
      <Dialog open={helpOpen} onClose={() => setHelpOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>How does this dashboard work?</DialogTitle>
        <DialogContent>
          <Typography variant="body1" sx={{ mb: 2 }}>
            This dashboard analyzes any web page for clickable elements, tests them, and reports which are working, dead, or error-prone. Use the <b>Run Test</b> button above to analyze a new URL. Dead clicks are shown with their location so anyone can find and fix them.
          </Typography>
          <Typography variant="body2" color="text.secondary">
            <b>For non-developers:</b> To find a dead click, copy the XPath or CSS selector from the table and paste it into your browser's DevTools (press <kbd>Cmd+F</kbd> or <kbd>Ctrl+F</kbd> in the Elements panel). This will highlight the problematic element visually.
          </Typography>
        </DialogContent>
      </Dialog>
      <Dialog open={showOptions} onClose={() => setShowOptions(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Detection Options</DialogTitle>
        <DialogContent>
          <Box sx={{ my: 2 }}>
            <Typography gutterBottom>Wait Time (seconds after load):</Typography>
            <TextField
              type="number"
              value={waitTime}
              onChange={e => setWaitTime(Number(e.target.value))}
              inputProps={{ min: 1, max: 30 }}
              fullWidth
              sx={{ mb: 2 }}
            />
            <Typography gutterBottom>Detection Strictness:</Typography>
            <TextField
              select
              SelectProps={{ native: true }}
              value={strictness}
              onChange={e => setStrictness(e.target.value)}
              fullWidth
            >
              <option value="normal">Normal</option>
              <option value="loose">Loose (find more, may include false positives)</option>
              <option value="strict">Strict (fewer, more certain clickables)</option>
            </TextField>
          </Box>
          <Button variant="contained" onClick={() => { setShowOptions(false); handleRunTest(); }} fullWidth>
            Run Test with These Settings
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default App;
