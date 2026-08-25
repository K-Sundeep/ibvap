import { useEffect, useRef, useState } from "react";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const WS_URL = BACKEND_URL.replace(/^http/, "ws") + "/ws/tracks";

export default function Home() {
  const [backendStatus, setBackendStatus] = useState("checking...");
  const [wsStatus, setWsStatus] = useState("connecting...");
  const [latestByCamera, setLatestByCamera] = useState({});
  const wsRef = useRef(null);

  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then((res) => res.json())
      .then((data) => setBackendStatus(data.status))
      .catch(() => setBackendStatus("unreachable"));
  }, []);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");
    ws.onerror = () => setWsStatus("error");

    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      setLatestByCamera((prev) => ({
        ...prev,
        [payload.camera_id]: payload,
      }));
    };

    return () => ws.close();
  }, []);

  const cameraIds = Object.keys(latestByCamera);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>IBVAP Dashboard</h1>
      <p>backend health: {backendStatus} | tracks websocket: {wsStatus}</p>

      {/* TODO Phase 1: replace this raw JSON dump with CameraTile grid
          (video frame + bbox overlay per camera) */}
      <h2>Live tracks by camera</h2>
      {cameraIds.length === 0 && <p>No track data received yet.</p>}
      {cameraIds.map((camId) => (
        <pre key={camId} style={{ background: "#f4f4f4", padding: "1rem" }}>
          {JSON.stringify(latestByCamera[camId], null, 2)}
        </pre>
      ))}

      {/* TODO Phase 2: FenceEditor, AlertsFeed */}
      {/* TODO Phase 2: EventLog */}
    </main>
  );
}
