// Tiny dependency-free static server for local development and browser tests.
var http = require('http');
var fs = require('fs');
var path = require('path');
var root = path.resolve(__dirname, '../public');
var types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml'};
http.createServer(function (req, res) {
  var pathname;
  try { pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname); }
  catch (e) { res.writeHead(400); res.end('Bad request'); return; }
  if (pathname === '/') pathname = '/index.html';
  var file = path.resolve(root, '.' + pathname);
  if (file !== root && file.indexOf(root + path.sep) !== 0) { res.writeHead(403); res.end('Forbidden'); return; }
  fs.readFile(file, function (err, data) {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    res.writeHead(200, {'Content-Type':types[path.extname(file)] || 'application/octet-stream','X-Content-Type-Options':'nosniff'});
    res.end(data);
  });
}).listen(Number(process.env.PORT || 4173), '127.0.0.1', function () {
  console.log('Kyro available at http://127.0.0.1:' + (process.env.PORT || 4173));
});
