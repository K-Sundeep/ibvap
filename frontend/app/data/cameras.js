/**
 * Camera roster for the dashboard.
 *
 * Placeholder data for Phase 0 — every tile points at the same static sample
 * clip so we can verify the grid renders. Once the backend is up this list
 * comes from GET /cameras and `src` becomes the HLS URL published by the
 * ingest service for that camera's RTSP stream.
 */
const SAMPLE_FEED = '/samples/sample-feed.mp4';

export const cameras = [
  { id: 'CAM-01', name: 'Main Gate', location: 'BOP Alpha — North', src: SAMPLE_FEED },
  { id: 'CAM-02', name: 'Perimeter East', location: 'BOP Alpha — Fence Line', src: SAMPLE_FEED },
  { id: 'CAM-03', name: 'Approach Road', location: 'BOP Alpha — South', src: SAMPLE_FEED },
  { id: 'CAM-04', name: 'Watchtower', location: 'BOP Alpha — West', src: SAMPLE_FEED },
];
