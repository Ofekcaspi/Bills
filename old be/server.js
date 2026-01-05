const http = require("http");

const server = http.createServer((req, res) => {
    if (req.url === "/api/hello") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ message: "Hello from backend" }));
        return;
    }

    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("Backend running");
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`Backend listening on http://localhost:${PORT}`));
