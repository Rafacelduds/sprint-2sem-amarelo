import { DEFAULT_VISUAL, type Visualization } from "../visualization";
const modes = [
  { value: "clusters", label: "Grupos", icon: "groups" },
  { value: "density", label: "Calor", icon: "heat" },
  { value: "mixed", label: "Misto", icon: "mixed" },
] as const;
export default function VisualizationControls({
  value,
  onChange,
}: {
  value: Visualization;
  onChange: (value: Visualization) => void;
}) {
  const groups = value.mode !== "density";
  return (
    <section className="visual-controls" aria-label="Visualização">
      <h2>Visualização</h2>
      <div
        className="visual-modes"
        role="group"
        aria-label="Modo de visualização"
      >
        {modes.map((mode) => (
          <button
            key={mode.value}
            aria-pressed={value.mode === mode.value}
            onClick={() => onChange({ ...value, mode: mode.value })}
          >
            <span
              className={`mode-icon mode-icon-${mode.icon}`}
              aria-hidden="true"
            />
            {mode.label}
          </button>
        ))}
      </div>
      <p className="mode-description">
        {value.mode === "clusters"
          ? "Explore os grupos e encontre cada ônibus."
          : value.mode === "density"
            ? "Veja onde as posições se concentram."
            : "Veja a concentração e explore os ônibus."}
      </p>
      {value.mode !== "clusters" && (
        <div className="visual-setting">
          <div className="setting-heading">
            <label htmlFor="heat-intensity">Intensidade do calor</label>
            <output htmlFor="heat-intensity">{value.heatIntensity}%</output>
          </div>
          <input
            id="heat-intensity"
            type="range"
            min="25"
            max="200"
            step="25"
            value={value.heatIntensity}
            onChange={(e) =>
              onChange({ ...value, heatIntensity: Number(e.target.value) })
            }
          />
          <div className="range-hints" aria-hidden="true">
            <span>Suave</span>
            <span>Forte</span>
          </div>
        </div>
      )}
      {groups && (
        <>
          <div className="visual-setting">
            <span className="setting-label" id="group-sizing-label">
              Tamanho dos grupos
            </span>
            <div
              className="size-choice"
              role="group"
              aria-labelledby="group-sizing-label"
            >
              <button
                aria-pressed={value.groupSizing === "proportional"}
                onClick={() =>
                  onChange({ ...value, groupSizing: "proportional" })
                }
              >
                Por quantidade
              </button>
              <button
                aria-pressed={value.groupSizing === "uniform"}
                onClick={() => onChange({ ...value, groupSizing: "uniform" })}
              >
                Mesmo tamanho
              </button>
            </div>
            <p>
              {value.groupSizing === "proportional"
                ? "Mais ônibus, círculos maiores."
                : "Todos os grupos com o mesmo tamanho."}
            </p>
          </div>
          <details className="visual-more">
            <summary>Mais opções</summary>
            <div className="visual-setting">
              <div className="setting-heading">
                <label htmlFor="cluster-size">Tamanho geral dos grupos</label>
                <output htmlFor="cluster-size">
                  {Math.round(value.groupScale * 100)}%
                </output>
              </div>
              <input
                id="cluster-size"
                type="range"
                min="100"
                max="150"
                step="10"
                value={Math.round(value.groupScale * 100)}
                onChange={(e) =>
                  onChange({
                    ...value,
                    groupScale: Number(e.target.value) / 100,
                  })
                }
              />
            </div>
            <div className="visual-setting">
              <div className="setting-heading">
                <label htmlFor="bus-size">Tamanho dos ônibus</label>
                <output htmlFor="bus-size">{value.busDiameter} px</output>
              </div>
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
            </div>
            <label className="color-choice">
              Cores dos grupos
              <select
                value={value.composition}
                onChange={(e) =>
                  onChange({
                    ...value,
                    composition: e.target.value as Visualization["composition"],
                  })
                }
              >
                <option value="proportional">Por quantidade de ônibus</option>
                <option value="equal">Uma fatia por cor</option>
              </select>
            </label>
          </details>
        </>
      )}
      <button
        className="reset-visual"
        onClick={() => onChange({ ...DEFAULT_VISUAL })}
      >
        Restaurar padrões
      </button>
    </section>
  );
}
