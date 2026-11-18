const http = require('node:http');
http.createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  res.setHeader('Content-Type', 'application/json');
  if (path.endsWith('/Login/Autenticar') && req.method === 'POST') {
    res.setHeader('Set-Cookie', 'session=synthetic; Path=/');
    return res.end('true');
  }
  if (path.endsWith('/Posicao') && req.method === 'GET') {
    if (!String(req.headers.cookie).includes('session=synthetic')) { res.statusCode = 401; return res.end('{}'); }
    return res.end(JSON.stringify({ hr: '12:00', l: [{ c: '5015-10', cl: 33887, sl: 2, lt0: 'METRÔ JABAQUARA', lt1: 'JD. SÃO JORGE', qv: 2, vs: [
      { p: 68021, a: true, ta: new Date().toISOString(), py: -23.5505, px: -46.6333 },
      { p: 68022, a: false, ta: new Date(Date.now() - 120000).toISOString(), py: -23.56, px: -46.645 }
    ] }] }));
  }
  res.statusCode = 501; res.end('{}');
}).listen(process.env.PORT);
