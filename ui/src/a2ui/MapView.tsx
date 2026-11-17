/**
 * Google Map of the tenant's block.
 *
 *  - With a Maps JavaScript API key (GOOGLE_MAPS_API_KEY on the API server): an interactive map with a
 *    red pin on the tenant's block and blue pins on each cited 311 record; click a pin for its id.
 *  - Without a key: Google Maps' keyless embed of the address, plus "open in Google Maps" links.
 *
 * Addresses are block level only ("600 John Muir Dr"): 311 data is redacted to the 100-block.
 */
import {useEffect, useRef, useState} from 'react';
import {ExternalLink, MapPin} from 'lucide-react';

type Marker = {id: string; label: string; lat: number; lng: number; kind: 'same_block' | 'nearby'};
type Props = {address?: string; center?: unknown; markers?: unknown; apiKey?: string; openUrl?: string};

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    google?: any;
    __a4iMapsReady?: () => void;
  }
}

let mapsPromise: Promise<any> | null = null;
function loadMaps(key: string): Promise<any> {
  if (window.google?.maps) return Promise.resolve(window.google.maps);
  mapsPromise ??= new Promise((resolve, reject) => {
    window.__a4iMapsReady = () => resolve(window.google.maps);
    const s = document.createElement('script');
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&callback=__a4iMapsReady`;
    s.async = true;
    s.onerror = () => {
      mapsPromise = null;
      reject(new Error('Google Maps failed to load'));
    };
    document.head.appendChild(s);
  });
  return mapsPromise;
}

function pin(maps: any, color: string, scale: number) {
  return {path: maps.SymbolPath.CIRCLE, fillColor: color, fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 2, scale};
}

export function MapView({address, center, markers, apiKey, openUrl}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const pins = (Array.isArray(markers) ? markers : []) as Marker[];
  const c = center && typeof center === 'object' ? (center as {lat: number; lng: number}) : null;
  const pinsKey = JSON.stringify(pins) + JSON.stringify(c) + address;

  useEffect(() => {
    if (!apiKey || !ref.current) return;
    let cancelled = false;
    const objects: any[] = [];
    loadMaps(apiKey)
      .then(async maps => {
        if (cancelled || !ref.current) return;
        let home = c;
        if (!home && address) {
          const geo = await new maps.Geocoder().geocode({address}).catch(() => null);
          const loc = geo?.results?.[0]?.geometry?.location;
          if (loc) home = {lat: loc.lat(), lng: loc.lng()};
        }
        const map = new maps.Map(ref.current, {
          center: home ?? {lat: 37.7749, lng: -122.4194},
          zoom: home ? 16 : 12,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
          clickableIcons: false,
        });
        const info = new maps.InfoWindow();
        const bounds = new maps.LatLngBounds();
        if (home) {
          const m = new maps.Marker({map, position: home, title: `Tenant block: ${address}`, icon: pin(maps, '#A61B1B', 9), zIndex: 10});
          m.addListener('click', () => {
            info.setContent(`<strong>Tenant block</strong><br>${address ?? ''}`);
            info.open({map, anchor: m});
          });
          objects.push(m);
          bounds.extend(home);
        }
        for (const p of pins) {
          if (p.kind === 'same_block' && home && Math.abs(p.lat - home.lat) < 1e-6 && Math.abs(p.lng - home.lng) < 1e-6) continue;
          const m = new maps.Marker({map, position: {lat: p.lat, lng: p.lng}, title: p.label, icon: pin(maps, '#1F4FD1', 7)});
          m.addListener('click', () => {
            info.setContent(`<strong>${p.id}</strong><br>${p.label.split(' · ')[1] ?? ''}<br><em>open 311 record</em>`);
            info.open({map, anchor: m});
          });
          objects.push(m);
          bounds.extend({lat: p.lat, lng: p.lng});
        }
        if (pins.length > 1) map.fitBounds(bounds, 48);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      objects.forEach(o => o.setMap(null));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, pinsKey]);

  if (!address) return <div className="nv-map nv-map-empty">No block logged for this case yet.</div>;

  const useEmbed = !apiKey || failed;
  const q = c ? `${c.lat},${c.lng}` : address;
  return (
    <div className="nv-map-wrap">
      {useEmbed ? (
        <iframe
          className="nv-map"
          title={`Google Map of ${address}`}
          src={`https://maps.google.com/maps?q=${encodeURIComponent(q)}&z=16&output=embed`}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
        />
      ) : (
        <div ref={ref} className="nv-map" role="region" aria-label={`Google Map of ${address}`} />
      )}
      <div className="nv-map-foot">
        <span className="nv-small">
          <MapPin size={13} aria-hidden="true" /> {address}
        </span>
        {openUrl ? (
          <a className="nv-small" href={openUrl} target="_blank" rel="noreferrer">
            Open in Google Maps <ExternalLink size={12} aria-hidden="true" />
          </a>
        ) : null}
      </div>
      {useEmbed && pins.length ? (
        <ul className="nv-map-pins">
          {pins.map(p => (
            <li key={p.id}>
              <span className={`nv-dot ${p.kind === 'same_block' ? 'is-home' : ''}`} aria-hidden="true" />
              <a href={`https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`} target="_blank" rel="noreferrer">
                {p.label}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
