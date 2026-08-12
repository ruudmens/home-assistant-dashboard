class GarageClimateCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._entity = null;
    this._isDragging = false;
    this._pendingTemp = null;
    this._debounceTimer = null;
    this._fanModes = [];
    this._swingModes = [];
  }

  setConfig(config) {
    if (!config.entity) throw new Error('Please define an entity');
    this._config = config;
    this._entity = config.entity;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._entity];
    if (!state) return;

    // Cache modes from attributes
    if (state.attributes.fan_modes) this._fanModes = state.attributes.fan_modes;
    if (state.attributes.swing_modes) this._swingModes = state.attributes.swing_modes;

    this.updateCard(state);
  }

  get entity() {
    return this._hass ? this._hass.states[this._entity] : null;
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;700&display=swap');

        :host {
          display: block;
          width: 225px;
          height: 450px;
        }

        .card {
          width: 225px;
          height: 450px;
          background: #161719;
          border-radius: 20px;
          overflow: hidden;
          position: relative;
          display: flex;
          flex-direction: column;
          align-items: center;
          font-family: 'DM Mono', monospace;
          box-shadow: 0 8px 32px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06);
        }

        /* Ambient glow that shifts with temp */
        .ambient {
          position: absolute;
          top: -60px;
          left: 50%;
          transform: translateX(-50%);
          width: 180px;
          height: 180px;
          border-radius: 50%;
          opacity: 0.12;
          filter: blur(40px);
          pointer-events: none;
          transition: background 0.6s ease;
        }

        /* Top section: entity name + current temp */
        .top-section {
          width: 100%;
          padding: 22px 20px 0;
          box-sizing: border-box;
          position: relative;
          z-index: 2;
        }

        /* Card header: icon + name/state row */
        .card-header {
          display: flex;
          align-items: center;
          gap: 9px;
          margin-bottom: 6px;
        }

        .icon-cell {
          background: #141414;
          border-radius: 16px;
          padding: 6px;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .card-icon {
          width: 24px;
          height: 24px;
          object-fit: contain;
        }

        .entity-name {
          font-family: 'Poppins', sans-serif;
          font-size: 18px;
          font-weight: 500;
          color: white;
          line-height: 1.2;
        }

        .card-state {
          font-family: 'Poppins', sans-serif;
          font-size: 12px;
          color: #5b5b5c;
          line-height: 1.4;
        }

        .current-temp {
          font-family: 'Poppins', sans-serif;
          font-size: 20px;
          font-weight: 500;
          color: #fff;
          line-height: 1;
        }

        .current-temp .unit {
          font-size: 10px;
          font-weight: 400;
          opacity: 0.5;
          vertical-align: super;
          margin-left: 2px;
        }

        /* Background image — flush left */
        .bg-image {
          position: absolute;
          left: 0;
          top: 70px;
          height: 70%;
          width: auto;
          z-index: 0;
          pointer-events: none;
        }

        /* Gradient overlay — fades image into card colour from left to right */
        .bg-overlay {
          position: absolute;
          inset: 0;
          background: linear-gradient(90deg, rgba(22,23,25,0.15) 0%, rgba(22,23,25,0.80) 50%, rgba(22,23,25,0.98) 100%);
          z-index: 1;
          pointer-events: none;
        }

        /* Middle section: slider area */
        .middle-section {
          flex: 1;
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          z-index: 2;
          padding: 10px 0;
        }

        /* Current temp shown in slider area — no label */
        .target-display {
          position: absolute;
          left: 90px;
          top: 30%;
          text-align: left;
        }

        .target-temp {
          font-family: 'Poppins', sans-serif;
          font-size: 20px;
          font-weight: 500;
          color: #fff;
          line-height: 1;
          transition: color 0.3s;
        }

        .target-temp .unit {
          font-size: 10px;
          opacity: 0.45;
          vertical-align: super;
        }

        /* Vertical slider track */
        .slider-container {
          position: absolute;
          left: 66%;
          width: 44px;
          height: 220px;
        }

        .slider-track {
          position: absolute;
          left: 50%;
          top: 0;
          transform: translateX(-50%);
          width: 10px;
          height: 100%;
          border-radius: 5px;
          background: rgba(255,255,255,0.07);
          overflow: visible;
        }

        .slider-fill {
          position: absolute;
          bottom: 0;
          left: 0;
          width: 100%;
          border-radius: 5px;
          transition: height 0.15s ease, background 0.4s ease;
        }

        .slider-thumb {
          position: absolute;
          left: 50%;
          transform: translate(-50%, 50%);
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: #fff;
          box-shadow: 0 2px 12px rgba(0,0,0,0.5), 0 0 0 3px rgba(255,255,255,0.15);
          cursor: grab;
          transition: transform 0.1s ease, box-shadow 0.2s ease, background 0.4s ease;
          z-index: 10;
          touch-action: none;
        }

        .slider-thumb:active { cursor: grabbing; }

        .slider-thumb.dragging {
          transform: translate(-50%, 50%) scale(1.15);
          box-shadow: 0 4px 20px rgba(0,0,0,0.6), 0 0 0 4px rgba(255,255,255,0.2);
        }

        /* Tick marks on the right side of track */
        .tick-marks {
          position: absolute;
          right: -14px;
          top: 0;
          height: 100%;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          pointer-events: none;
        }

        .tick {
          display: flex;
          align-items: center;
          gap: 3px;
        }

        .tick-line {
          width: 5px;
          height: 1px;
          background: rgba(255,255,255,0.15);
        }

        .tick-line.major {
          width: 8px;
          background: rgba(255,255,255,0.3);
        }

        .tick-val {
          font-size: 7px;
          color: rgba(255,255,255,0.2);
          letter-spacing: 0.05em;
          min-width: 14px;
        }

        /* Bottom buttons */
        .buttons-section {
          width: 100%;
          padding: 0 18px 22px;
          box-sizing: border-box;
          display: flex;
          flex-direction: column;
          gap: 8px;
          position: relative;
          z-index: 2;
        }

        .btn-row {
          display: flex;
          gap: 8px;
          justify-content: center;
        }

        .btn {
          width: 56px;
          height: 56px;
          border: none;
          border-radius: 12px;
          background: #121212;
          color: rgba(255,255,255,0.55);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s ease;
          position: relative;
          overflow: hidden;
        }

        .btn:hover { background: #1c1c1e; }
        .btn:active { transform: scale(0.94); }

        .btn.power-on {
          background: rgba(46,218,210,0.15);
          color: #2edad2;
        }

        .btn.power-off {
          background: #121212;
          color: rgba(255,255,255,0.35);
        }

        .btn-icon {
          width: 24px;
          height: 24px;
          object-fit: contain;
        }

        /* Divider */
        .divider {
          width: calc(100% - 36px);
          height: 1px;
          background: rgba(255,255,255,0.05);
          margin: 0 18px 8px;
          position: relative;
          z-index: 2;
        }

        /* Modal overlay for mode selection */
        .modal {
          display: none;
          position: absolute;
          inset: 0;
          background: rgba(22,23,25,0.95);
          border-radius: 20px;
          z-index: 100;
          flex-direction: column;
          padding: 20px;
          box-sizing: border-box;
          backdrop-filter: blur(4px);
        }

        .modal.open { display: flex; }

        .modal-title {
          font-family: 'Syne', sans-serif;
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0.15em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.4);
          margin-bottom: 14px;
        }

        .modal-options {
          display: flex;
          flex-direction: column;
          gap: 6px;
          flex: 1;
          overflow-y: auto;
        }

        .modal-option {
          padding: 10px 14px;
          border-radius: 10px;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.05);
          color: rgba(255,255,255,0.6);
          font-family: 'DM Mono', monospace;
          font-size: 10px;
          letter-spacing: 0.08em;
          cursor: pointer;
          transition: all 0.15s;
          text-transform: capitalize;
        }

        .modal-option:hover {
          background: rgba(255,255,255,0.1);
          color: #fff;
        }

        .modal-option.selected {
          background: rgba(46,218,210,0.12);
          color: #2edad2;
          border-color: rgba(46,218,210,0.3);
        }

        .modal-close {
          margin-top: 12px;
          padding: 10px;
          border-radius: 10px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
          color: rgba(255,255,255,0.3);
          font-family: 'DM Mono', monospace;
          font-size: 9px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          cursor: pointer;
          text-align: center;
          transition: all 0.15s;
        }

        .modal-close:hover {
          background: rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.6);
        }
      </style>

      <div class="card">
        <div class="ambient" id="ambient"></div>
        <img class="bg-image" id="bgImage" src="" alt=""/>
        <div class="bg-overlay"></div>

        <!-- Top: icon + name/state + target temp -->
        <div class="top-section">
          <div class="card-header">
            <div class="icon-cell">
              <img class="card-icon" id="cardIcon" src="" alt=""/>
            </div>
            <div>
              <div class="entity-name" id="entityName">Heat Pump</div>
              <div class="card-state" id="cardState">Off</div>
            </div>
          </div>
        </div>

        <!-- Middle: current temp (no label) + slider -->
        <div class="middle-section">
          <div class="target-display">
            <div class="target-temp" id="targetTemp">--<span class="unit">°C</span></div>
          </div>

          <div class="slider-container" id="sliderContainer">
            <div class="slider-track" id="sliderTrack">
              <div class="slider-fill" id="sliderFill"></div>
              <div class="slider-thumb" id="sliderThumb"></div>
            </div>
            <div class="tick-marks" id="tickMarks"></div>
          </div>
        </div>

        <!-- Bottom: 3 icon-only buttons in one row -->
        <div class="buttons-section">
          <div class="btn-row">
            <button class="btn" id="btnPower"><img class="btn-icon" id="iconPower" src="/local/assets/icons/power-off.png" alt="power"/></button>
            <button class="btn" id="btnFan"><img class="btn-icon" id="iconFan" src="/local/assets/icons/fan-off.png" alt="fan"/></button>
            <button class="btn" id="btnSwing"><img class="btn-icon" id="iconSwing" src="/local/assets/icons/swiffle-off.png" alt="swing"/></button>
          </div>
        </div>

        <!-- Mode modals -->
        <div class="modal" id="modalFan">
          <div class="modal-title">Fan Mode</div>
          <div class="modal-options" id="modalFanOptions"></div>
          <div class="modal-close" id="modalFanClose">Close</div>
        </div>

        <div class="modal" id="modalSwing">
          <div class="modal-title">Swing Mode</div>
          <div class="modal-options" id="modalSwingOptions"></div>
          <div class="modal-close" id="modalSwingClose">Close</div>
        </div>
      </div>
    `;

    this._buildTicks();
    this._attachEvents();
  }

  _buildTicks() {
    const container = this.shadowRoot.getElementById('tickMarks');
    if (!container) return;
    container.innerHTML = '';
    // Show ticks at every 1 degree, label every 5
    const MIN = 8, MAX = 25;
    const steps = MAX - MIN;
    for (let i = MAX; i >= MIN; i--) {
      const tick = document.createElement('div');
      tick.className = 'tick';
      const isMajor = i % 5 === 0;
      tick.innerHTML = `
        <div class="tick-line ${isMajor ? 'major' : ''}"></div>
        <span class="tick-val">${isMajor ? i : ''}</span>
      `;
      container.appendChild(tick);
    }
  }

  _attachEvents() {
    const thumb = this.shadowRoot.getElementById('sliderThumb');
    const track = this.shadowRoot.getElementById('sliderTrack');

    // Power button
    this.shadowRoot.getElementById('btnPower').addEventListener('click', () => {
      const state = this.entity;
      if (!state) return;
      const isOn = state.state !== 'off';
      this._hass.callService('climate', isOn ? 'turn_off' : 'turn_on', {
        entity_id: this._entity
      });
    });

    // Fan button — cycle to next mode on tap
    this.shadowRoot.getElementById('btnFan').addEventListener('click', () => {
      const state = this.entity;
      if (!state || state.state === 'off') return;
      const modes = this._fanModes;
      if (!modes.length) return;
      const current = state.attributes.fan_mode;
      const idx = modes.indexOf(current);
      const nextMode = modes[(idx + 1) % modes.length];
      this._hass.callService('climate', 'set_fan_mode', {
        entity_id: this._entity,
        fan_mode: nextMode
      });
    });

    // Swing button
    this.shadowRoot.getElementById('btnSwing').addEventListener('click', () => {
      this._openModal('swing');
    });

    // Modal closes
    this.shadowRoot.getElementById('modalFanClose').addEventListener('click', () => {
      this.shadowRoot.getElementById('modalFan').classList.remove('open');
    });
    this.shadowRoot.getElementById('modalSwingClose').addEventListener('click', () => {
      this.shadowRoot.getElementById('modalSwing').classList.remove('open');
    });

    // Slider drag — pointer events (works for both mouse and touch)
    thumb.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      thumb.setPointerCapture(e.pointerId);
      thumb.classList.add('dragging');
      this._isDragging = true;
    });

    thumb.addEventListener('pointermove', (e) => {
      if (!this._isDragging) return;
      const rect = track.getBoundingClientRect();
      const relY = e.clientY - rect.top;
      const pct = Math.min(1, Math.max(0, relY / rect.height));
      const temp = this._pctToTemp(1 - pct);
      this._pendingTemp = temp;
      this._updateSliderVisuals(temp);
      this._updateTargetDisplay(temp);
    });

    thumb.addEventListener('pointerup', () => {
      thumb.classList.remove('dragging');
      this._isDragging = false;
      if (this._pendingTemp !== null) {
        this._commitTemp(this._pendingTemp);
        this._pendingTemp = null;
      }
    });
  }

  _openModal(type) {
    const state = this.entity;
    if (!state) return;

    if (type === 'fan') {
      const modes = this._fanModes;
      const current = state.attributes.fan_mode;
      const container = this.shadowRoot.getElementById('modalFanOptions');
      container.innerHTML = '';
      modes.forEach(mode => {
        const opt = document.createElement('div');
        opt.className = `modal-option ${mode === current ? 'selected' : ''}`;
        opt.textContent = mode;
        opt.addEventListener('click', () => {
          this._hass.callService('climate', 'set_fan_mode', {
            entity_id: this._entity,
            fan_mode: mode
          });
          this.shadowRoot.getElementById('modalFan').classList.remove('open');
        });
        container.appendChild(opt);
      });
      this.shadowRoot.getElementById('modalFan').classList.add('open');
    } else {
      const modes = this._swingModes;
      const current = state.attributes.swing_mode;
      const container = this.shadowRoot.getElementById('modalSwingOptions');
      container.innerHTML = '';
      modes.forEach(mode => {
        const opt = document.createElement('div');
        opt.className = `modal-option ${mode === current ? 'selected' : ''}`;
        opt.textContent = mode;
        opt.addEventListener('click', () => {
          this._hass.callService('climate', 'set_swing_mode', {
            entity_id: this._entity,
            swing_mode: mode
          });
          this.shadowRoot.getElementById('modalSwing').classList.remove('open');
        });
        container.appendChild(opt);
      });
      this.shadowRoot.getElementById('modalSwing').classList.add('open');
    }
  }

  _pctToTemp(pct) {
    const MIN = 8, MAX = 25;
    // Round to nearest 0.5
    const raw = MIN + pct * (MAX - MIN);
    return Math.round(raw * 2) / 2;
  }

  _tempToPct(temp) {
    const MIN = 8, MAX = 25;
    return (temp - MIN) / (MAX - MIN);
  }

  _tempToColor(temp) {
    // Interpolate between cold #2edad2 and warm #ffbf7b
    const MIN = 8, MAX = 25;
    const t = Math.min(1, Math.max(0, (temp - MIN) / (MAX - MIN)));
    const r = Math.round(0x2e + t * (0xff - 0x2e));
    const g = Math.round(0xda + t * (0xbf - 0xda));
    const b = Math.round(0xd2 + t * (0x7b - 0xd2));
    return `rgb(${r},${g},${b})`;
  }

  _updateSliderVisuals(temp) {
    const pct = this._tempToPct(temp);
    const trackHeight = 220; // matches CSS
    const thumbPos = (1 - pct) * trackHeight;

    const thumb = this.shadowRoot.getElementById('sliderThumb');
    const fill = this.shadowRoot.getElementById('sliderFill');
    const ambient = this.shadowRoot.getElementById('ambient');

    const color = this._tempToColor(temp);

    if (thumb) thumb.style.bottom = `${pct * 100}%`;
    if (fill) {
      fill.style.height = `${pct * 100}%`;
      fill.style.background = `linear-gradient(to top, #2edad2, ${color})`;
    }
    if (thumb) thumb.style.background = color;
    if (ambient) ambient.style.background = color;
  }

  _updateTargetDisplay(temp) {
    const el = this.shadowRoot.getElementById('targetTemp');
    if (el) {
      el.innerHTML = `${temp}<span class="unit">°C</span>`;
      el.style.color = this._tempToColor(temp);
    }
  }

  _commitTemp(temp) {
    clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => {
      this._hass.callService('climate', 'set_temperature', {
        entity_id: this._entity,
        temperature: temp
      });
    }, 300);
  }

  updateCard(state) {
    if (!state || this._isDragging) return;

    const isOn = state.state !== 'off';
    const currentTemp = state.attributes.current_temperature;
    const targetTemp = state.attributes.temperature;
    const fanMode = state.attributes.fan_mode || '—';
    const swingMode = state.attributes.swing_mode || '—';
    const hvacAction = state.attributes.hvac_action || state.state;

    // Background image
    const bgImage = this.shadowRoot.getElementById('bgImage');
    if (bgImage) bgImage.src = `/local/assets/${isOn ? 'heatpump-on' : 'heatpump-off'}.png`;

    // Card icon
    const cardIcon = this.shadowRoot.getElementById('cardIcon');
    if (cardIcon) cardIcon.src = `/local/assets/icons/${isOn ? 'heating-on' : 'heating-off'}.png`;

    // Entity name
    const nameEl = this.shadowRoot.getElementById('entityName');
    if (nameEl) nameEl.textContent = this._config.name || state.attributes.friendly_name || 'Climate';

    // Card state text
    const cardState = this.shadowRoot.getElementById('cardState');
    if (cardState) {
      const labels = { heating: 'Heating', cooling: 'Cooling', fan_only: 'Fan only', idle: 'Idle', off: 'Off' };
      cardState.textContent = labels[hvacAction] || hvacAction;
    }

    // Top display: shows TARGET temp
    const currentTempEl = this.shadowRoot.getElementById('currentTemp');
    if (currentTempEl) {
      currentTempEl.innerHTML = targetTemp != null
        ? `${targetTemp}<span class="unit">°C</span>`
        : `—<span class="unit">°C</span>`;
    }

    // Power button styling + icon
    const btnPower = this.shadowRoot.getElementById('btnPower');
    if (btnPower) btnPower.className = `btn ${isOn ? 'power-on' : 'power-off'}`;
    const iconPower = this.shadowRoot.getElementById('iconPower');
    if (iconPower) iconPower.src = `/local/assets/icons/${isOn ? 'power-on' : 'power-off'}.png`;

    // Fan icon
    const iconFan = this.shadowRoot.getElementById('iconFan');
    if (iconFan) iconFan.src = `/local/assets/icons/${isOn ? 'fan-on' : 'fan-off'}.png`;

    // Swing icon
    const iconSwing = this.shadowRoot.getElementById('iconSwing');
    if (iconSwing) iconSwing.src = `/local/assets/icons/${isOn ? 'swiffle-on' : 'swiffle-off'}.png`;

    // Slider driven by target temp; middle display shows CURRENT temp
    if (targetTemp != null) this._updateSliderVisuals(targetTemp);
    if (currentTemp != null) this._updateTargetDisplay(currentTemp);
  }

  static getConfigElement() {
    return document.createElement('garage-climate-card-editor');
  }

  static getStubConfig() {
    return { entity: 'climate.garage' };
  }
}

customElements.define('garage-climate-card', GarageClimateCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'garage-climate-card',
  name: 'Garage Climate Card',
  description: 'Custom climate card with vertical temperature slider',
});