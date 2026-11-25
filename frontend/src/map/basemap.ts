import type { StyleSpecification } from 'maplibre-gl';

export function atlasStyle(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    name: 'Waypoint Atlas',
    layers: style.layers.map((layer) => {
      if (layer.type === 'background') {
        return { ...layer, paint: { ...layer.paint, 'background-color': '#f4f4ed' } };
      }
      if (layer.id === 'water' && layer.type === 'fill') {
        return { ...layer, paint: { ...layer.paint, 'fill-color': '#d8e6e3' } };
      }
      if (layer.id === 'natural_earth' && layer.type === 'raster') {
        return { ...layer, paint: { ...layer.paint, 'raster-opacity': ['interpolate', ['linear'], ['zoom'], 0, 0.18, 6, 0.05] } };
      }
      if (layer.id === 'boundary_2' && layer.type === 'line') {
        return { ...layer, paint: { ...layer.paint, 'line-color': '#80917e', 'line-opacity': 0.85 } };
      }
      if (layer.type !== 'symbol' || layer.layout?.['text-field'] === undefined) return layer;

      const place = layer['source-layer'] === 'place';
      const country = place && layer.id.startsWith('label_country');
      return {
        ...layer,
        layout: {
          ...layer.layout,
          ...(place ? { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name_en'], ['get', 'name:latin'], ['get', 'name']] } : {}),
          ...(country ? {
            'text-font': ['Noto Sans Regular'],
            'text-size': ['interpolate', ['linear'], ['zoom'], 1, layer.id.endsWith('_3') ? 10 : 11, 5, 14],
            'text-letter-spacing': 0.03,
            'text-transform': 'none',
          } : {}),
        },
        paint: {
          ...layer.paint,
          'text-halo-color': '#fcfcf9',
          'text-halo-width': 1.5,
          'text-halo-blur': 0.5,
          ...(place ? { 'text-color': country ? '#3e5844' : '#35483a', 'text-opacity': 1 } : {}),
        },
      };
    }),
  };
}
