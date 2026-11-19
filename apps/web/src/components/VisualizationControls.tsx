import { DEFAULT_VISUAL, type Visualization } from "../visualization";
export default function VisualizationControls({
  value,
  onChange,
}: {
  value: Visualization;
  onChange: (value: Visualization) => void;
}) {
  return (
    <details className="visual-controls">
      <summary>Visualização</summary>
      <label>
        Modo de visualização
        <select
          value={value.mode}
          onChange={(e) =>
            onChange({
              ...value,
              mode: e.target.value as Visualization["mode"],
            })
          }
        >
          <option value="clusters">Agrupamentos</option>
          <option value="density">Densidade</option>
          <option value="mixed">Misto</option>
        </select>
      </label>
      <fieldset disabled={value.mode === "density"}>
        <legend>Ônibus e agrupamentos</legend>
        <label>
          Composição dos anéis
          <select
            value={value.composition}
            onChange={(e) =>
              onChange({
                ...value,
                composition: e.target.value as Visualization["composition"],
              })
            }
          >
            <option value="proportional">Proporção de ônibus</option>
            <option value="equal">Fatias iguais por cor</option>
          </select>
        </label>
        <label htmlFor="cluster-size">
          Tamanho dos grupos{" "}
          <output>{Math.round(value.groupScale * 100)}%</output>
          <input
            id="cluster-size"
            type="range"
            min="100"
            max="150"
            step="10"
            value={Math.round(value.groupScale * 100)}
            onChange={(e) =>
              onChange({ ...value, groupScale: Number(e.target.value) / 100 })
            }
          />
        </label>
        <label htmlFor="bus-size">
          Tamanho dos ônibus <output>{value.busDiameter} px</output>
          <input
            id="bus-size"
            type="range"
            min="9"
            max="18"
            step="1"
            value={value.busDiameter}
            onChange={(e) =>
              onChange({ ...value, busDiameter: Number(e.target.value) })
            }
          />
        </label>
      </fieldset>
      <button onClick={() => onChange({ ...DEFAULT_VISUAL })}>
        Restaurar padrões
      </button>
      <p>
        Preferências salvas neste navegador. O tamanho visual não altera os
        grupos.
      </p>
    </details>
  );
}
