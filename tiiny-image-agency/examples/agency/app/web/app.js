// Tiiny Image Agency — the work surface.
//
// The surface is an HTTP CLIENT of the agency, exactly like the CLI. It
// never touches the appliance and never holds a credential: the bearer
// lives on the server, and the browser only ever talks to the agency.
//
// THE ONE THING THAT WILL BITE YOU
// --------------------------------
// The event bus REPLAYS a session's recent events to a late subscriber,
// so that a client which opens the stream after the job was posted still
// catches up. That is a feature, and it has a sharp edge: the replay
// brings the terminal events of EARLIER jobs in the same session.
//
// An earlier build of the CLI did not filter by job id, and a second
// generation returned the FIRST generation's picture, byte for byte, in
// under a second, without generating anything at all. So:
//
//   * the stream is opened with ?job_id=<the id we were given>, and
//   * every event whose data.job_id is not ours is ignored.
//
// The swap events carry no job id at all. They are shown, but they never
// decide anything.

const API = new URLSearchParams(window.location.search).get('api')
    || window.location.origin;

// The agency's own session. Every surface shares it, so the events of
// one job are the events of the next.
const SESSION = 'default';

const $ = (id) => document.getElementById(id);

const els = {
    log: $('log'),
    composer: $('composer'),
    request: $('request'),
    feedbackForm: $('feedback-form'),
    feedback: $('feedback'),
    banner: $('swap-banner'),
    bannerText: $('swap-text'),
    bannerTime: $('swap-time'),
    npuFill: $('npu-fill'),
    npuText: $('npu-text'),
    npuResident: $('npu-resident'),
    modelId: $('model-id'),
    modelJustification: $('model-justification'),
    modelMeasured: $('model-measured'),
    image: $('generated-image'),
    placeholder: $('image-placeholder'),
    thumbs: $('thumbs'),
    lineage: $('lineage-body'),
    roleConversation: $('role-conversation'),
    roleCritic: $('role-critic'),
    roleNote: $('role-note'),
    modelAlternatives: $('model-alternatives'),
    dropzone: $('dropzone'),
    fileInput: $('file-input'),
    dropzoneSource: $('dropzone-source'),
    sourcePreview: $('source-preview'),
    sourceName: $('source-name'),
    sourcePath: $('source-path'),
    sourceClear: $('source-clear'),
    filePath: $('file-path'),
    cardGrid: $('card-grid'),
    cardDetail: $('card-detail'),
    cardSearch: $('card-search'),
    cardFilterArtifact: $('card-filter-artifact'),
    cardFilterMeasured: $('card-filter-measured'),
    referenceGrid: $('reference-grid'),
    dialogBackdrop: $('dialog-backdrop'),
    dialogModel: $('dialog-model'),
    dialogWhy: $('dialog-why'),
    dialogCost: $('dialog-cost'),
    dialogAlts: $('dialog-alts'),
    dialogCancel: $('dialog-cancel'),
    dialogGo: $('dialog-go'),
};

// The model the user chose, if any. Empty means "the resolver decides".
// It survives between requests: choosing a model is a standing
// preference, not a one-off.
let chosenModelId = '';

// The request the dialog is asking about.
let lastRequest = '';

// The image the user dropped in, if any. When it is set, the next
// request is an EDIT of that image rather than a new one.
let sourceAssetId = '';
let sourceAssetPath = '';

let currentJobId = null;
let currentAssetId = null;
let stream = null;
let bannerTimer = null;
let bannerStartedAt = null;
// Set once OUR job has been seen starting. The generate.* and
// critique.ready events carry NO job id, so they cannot be scoped to a
// job on their own — without this gate a replayed one from an earlier
// job would print a false "Generating with..." line.
let armed = false;

// -- the API -------------------------------------------------------------

async function apiGet(path) {
    const response = await fetch(API + path);
    if (!response.ok) {
        return null;
    }
    return response.json();
}

async function apiPost(path, body) {
    const response = await fetch(API + path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const text = await response.text();
    let payload = null;
    try {
        payload = text ? JSON.parse(text) : null;
    } catch (error) {
        payload = {detail: text};
    }
    if (!response.ok) {
        const detail = (payload && (payload.detail || payload.error))
            || response.status;
        throw new Error(detail);
    }
    return payload;
}

// -- the conversation ----------------------------------------------------

function say(text, kind) {
    const line = document.createElement('div');
    line.className = 'line ' + (kind || '');
    line.textContent = text;
    els.log.appendChild(line);
    els.log.scrollTop = els.log.scrollHeight;
    return line;
}

async function submit(event) {
    event.preventDefault();
    const request = els.request.value.trim();
    if (!request) {
        return;
    }
    els.request.value = '';
    say(request, 'ask');
    lastRequest = request;

    // An image was dropped in, so this is an EDIT of that image rather
    // than a new picture. The flow is the iteration flow: the asset is
    // the source, the request is the feedback.
    if (sourceAssetId) {
        await startEdit(sourceAssetId, request);
        return;
    }

    // Plan first, and then ASK. A generation costs a minute and
    // sometimes three, and the plan is where the agency says what it
    // is about to do and why. The user gets to see that, and to change
    // it, before anything is spent.
    let plan;
    try {
        plan = await apiPost('/v1/plan', {request, model_id: chosenModelId});
        renderPlan(plan);
    } catch (error) {
        say('The plan failed: ' + error.message, 'bad');
        return;
    }

    openDialog(plan, request);
}

async function startEdit(assetId, feedback) {
    try {
        const queued = await apiPost('/v1/iterate', {
            asset_id: assetId,
            feedback: feedback,
        });
        currentJobId = queued.job_id;
        watch(currentJobId);
    } catch (error) {
        say('The revision was refused: ' + error.message, 'bad');
    }
}

async function openDialog(plan, request) {
    const model = plan.model || {};
    els.dialogModel.textContent = model.id || '—';
    els.dialogWhy.textContent = plan.justification || '';

    if (plan.download) {
        const gib = ((plan.download.size_bytes || 0)
            / (1024 * 1024 * 1024)).toFixed(1);
        els.dialogCost.hidden = false;
        els.dialogCost.textContent = plan.download.model + ' is not on the '
            + 'appliance yet. It will be downloaded first — about '
            + gib + ' GiB, five minutes.';
    } else {
        els.dialogCost.hidden = true;
    }

    els.dialogAlts.innerHTML = '';
    const alternatives = plan.alternatives || [];
    for (const alternative of alternatives) {
        const button = document.createElement('button');
        const onDevice = alternative.downloaded ? '' : ', needs a download';
        button.className = 'alt';
        button.textContent = alternative.id + '  ('
            + alternative.npu_usage + '%' + onDevice + ')';
        button.addEventListener('click', () => {
            chosenModelId = alternative.id;
            els.dialogBackdrop.hidden = true;
            say('Using ' + alternative.id + '.', 'event');
            startGeneration(request, alternative.id);
        });
        els.dialogAlts.appendChild(button);
    }

    els.dialogBackdrop.hidden = false;
    els.dialogGo.focus();
}

async function startGeneration(request, modelId) {
    try {
        const queued = await apiPost('/v1/generate',
            {request, model_id: modelId || chosenModelId});
        currentJobId = queued.job_id;
        watch(currentJobId);
    } catch (error) {
        say('The request was refused: ' + error.message, 'bad');
    }
}

async function revise(event) {
    event.preventDefault();
    const feedback = els.feedback.value.trim();
    if (!feedback || !currentAssetId) {
        return;
    }
    els.feedback.value = '';
    say('→ ' + feedback, 'ask');

    try {
        const queued = await apiPost('/v1/iterate', {
            asset_id: currentAssetId,
            feedback: feedback,
        });
        currentJobId = queued.job_id;
        watch(currentJobId);
    } catch (error) {
        say('The revision was refused: ' + error.message, 'bad');
    }
}

// -- the drop zone --------------------------------------------------------

// An image the user dropped in. It is uploaded, kept byte for byte,
// and becomes the source of the next request - so the request is an
// EDIT of that image, not a new picture.
async function uploadSource(file) {
    if (!file) {
        return;
    }
    if (!file.type || file.type !== 'image/png') {
        say('Only a PNG can be dropped in — ' + file.name + ' is not one.',
            'bad');
        return;
    }
    try {
        const response = await fetch(API + '/v1/assets', {
            method: 'POST',
            headers: {'Content-Type': 'image/png'},
            body: file,
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || 'the upload was refused');
        }
        sourceAssetId = payload.asset_id;
        sourceAssetPath = payload.path || '';
        els.sourcePreview.src = URL.createObjectURL(file);
        els.sourceName.textContent = file.name;
        els.sourcePath.textContent = payload.path || '';
        els.dropzoneSource.classList.remove('hidden');
        say('Loaded ' + file.name + '. The next request updates it.',
            'event');
    } catch (error) {
        say('The image could not be loaded: ' + error.message, 'bad');
    }
}

function clearSource() {
    sourceAssetId = '';
    sourceAssetPath = '';
    els.dropzoneSource.classList.add('hidden');
    els.sourcePreview.removeAttribute('src');
}

// -- the tabs -------------------------------------------------------------

// Three kinds of work, three places. The Models tab is where a person
// goes to LEARN what the models are, so it is a tab of its own and not
// something buried under the generator.
const TAB_LOADERS = {};

function showTab(name) {
    for (const tab of document.querySelectorAll('.tab')) {
        const active = tab.dataset.tab === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', String(active));
    }
    for (const panel of document.querySelectorAll('.panel')) {
        panel.classList.toggle('hidden', panel.id !== 'panel-' + name);
    }
    // The tab's content is fetched the FIRST time it is opened, not at
    // page load. Seventeen cards is one request, but it is still a
    // request, and the Make tab does not need it.
    const loader = TAB_LOADERS[name];
    if (loader && !loader.done) {
        loader.done = true;
        loader.run();
    }
}

function wireTabs() {
    for (const tab of document.querySelectorAll('.tab')) {
        tab.addEventListener('click', () => showTab(tab.dataset.tab));
    }
}

// -- the model cards ------------------------------------------------------

// Every model in the catalogue has a card: what the device says it is
// for, what we measured, and what we have noticed that the device does
// not say. The third part is the point.
async function loadModelCard(modelId) {
    if (!modelId) {
        return;
    }
    const card = await apiGet('/v1/models/card?model_id='
        + encodeURIComponent(modelId));
    els.cardDetail.innerHTML = '';
    if (!card) {
        els.cardDetail.textContent = 'No card for ' + modelId + '.';
        return;
    }

    const head = document.createElement('p');
    head.className = 'card-model';
    head.textContent = card.model_id;
    els.cardDetail.appendChild(head);

    const status = document.createElement('p');
    status.className = 'card-status';
    status.textContent = (card.npu_usage || 0) + '% of the NPU · '
        + (card.downloaded ? 'on the appliance' : 'not on the appliance yet')
        + ' · ' + (card.researched ? 'measured' : 'not measured yet');
    els.cardDetail.appendChild(status);

    const advertised = document.createElement('div');
    advertised.className = 'card-part';
    const advertisedLabel = document.createElement('h4');
    advertisedLabel.textContent = 'What the device says';
    advertised.appendChild(advertisedLabel);
    const advertisedText = document.createElement('p');
    advertisedText.textContent = card.advertised
        || 'The device says nothing about this model.';
    advertised.appendChild(advertisedText);
    els.cardDetail.appendChild(advertised);

    if (card.measured) {
        const measured = document.createElement('div');
        measured.className = 'card-part';
        const measuredLabel = document.createElement('h4');
        measuredLabel.textContent = 'What we measured';
        measured.appendChild(measuredLabel);
        const measuredText = document.createElement('p');
        const bits = [];
        if (card.measured.summary) {
            bits.push(card.measured.summary);
        }
        if (card.measured.artifacts
            && card.measured.artifacts.length) {
            bits.push('artifacts: ' + card.measured.artifacts.join(', '));
        }
        if (card.measured.alpha === 'yes') {
            bits.push('transparent background ('
                + card.measured.transparent_pct + '%)');
        } else if (card.measured.alpha === 'no') {
            bits.push('opaque background');
        }
        if (card.measured.text_rendering === 'best') {
            bits.push('legible text');
        }
        measuredText.textContent = bits.join(' · ') || '—';
        measured.appendChild(measuredText);
        els.cardDetail.appendChild(measured);
    }

    const notes = document.createElement('div');
    notes.className = 'card-part card-notes';
    const notesLabel = document.createElement('h4');
    notesLabel.textContent = 'What we have noticed';
    notes.appendChild(notesLabel);
    const notesText = document.createElement('p');
    notesText.textContent = card.notes
        || 'Nothing yet — this model has not been characterised.';
    notes.appendChild(notesText);
    els.cardDetail.appendChild(notes);
}

// Every card, in ONE request. Seventeen separate requests to draw one
// grid is a grid that arrives in pieces.
let allCards = null;

async function loadAllCards() {
    const data = await apiGet('/v1/models/cards');
    if (!data) {
        return;
    }
    allCards = data.cards || [];
    fillArtifactFilter(allCards);
    renderCardGrid();
    if (allCards.length) {
        showCardDetail(allCards[0]);
    }
}

// The kind of picture a model is good at — the filter a person would
// actually reach for ("I want a photo").
function fillArtifactFilter(cards) {
    const kinds = new Set();
    for (const card of cards) {
        for (const artifact of (card.artifact || [])) {
            kinds.add(artifact);
        }
    }
    els.cardFilterArtifact.innerHTML = '';
    const any = document.createElement('option');
    any.value = '';
    any.textContent = 'any kind of picture';
    els.cardFilterArtifact.appendChild(any);
    for (const kind of [...kinds].sort()) {
        const option = document.createElement('option');
        option.value = kind;
        option.textContent = kind;
        els.cardFilterArtifact.appendChild(option);
    }
}

// The grid is for BROWSING: what each model costs and what it can do,
// at a glance. The detail pane is where one is read.
function renderCardGrid() {
    els.cardGrid.innerHTML = '';
    if (!allCards) {
        return;
    }
    const search = (els.cardSearch.value || '').trim().toLowerCase();
    const artifact = els.cardFilterArtifact.value || '';
    const measured = els.cardFilterMeasured.value || '';

    const shown = allCards.filter((card) => {
        if (measured === 'measured' && !card.researched) {
            return false;
        }
        if (measured === 'unmeasured' && card.researched) {
            return false;
        }
        if (artifact && !(card.artifact || []).includes(artifact)) {
            return false;
        }
        if (search) {
            const haystack = [
                card.model_id,
                card.role,
                card.measured && card.measured.summary,
                (card.artifact || []).join(' '),
            ].filter(Boolean).join(' ').toLowerCase();
            if (!haystack.includes(search)) {
                return false;
            }
        }
        return true;
    });

    if (!shown.length) {
        const empty = document.createElement('p');
        empty.className = 'card-empty';
        empty.textContent = allCards.length
            ? 'No model matches that.'
            : 'No models in the catalogue yet.';
        els.cardGrid.appendChild(empty);
        return;
    }

    for (const card of shown) {
        els.cardGrid.appendChild(cardTile(card));
    }
}

function cardTile(card) {
    const tile = document.createElement('button');
    tile.type = 'button';
    tile.className = 'card-tile';
    tile.dataset.model = card.model_id;

    const name = document.createElement('span');
    name.className = 'card-tile-name';
    name.textContent = card.model_id;
    tile.appendChild(name);

    const facts = document.createElement('span');
    facts.className = 'card-tile-facts';
    const bits = [card.npu_usage + '%'];
    if (card.speed && card.speed !== 'unknown') {
        bits.push(card.speed);
    }
    if (card.alpha) {
        bits.push('transparent');
    }
    facts.textContent = bits.join(' · ');
    tile.appendChild(facts);

    const badge = document.createElement('span');
    badge.className = 'card-tile-badge' + (card.researched ? ' measured' : '');
    badge.textContent = card.researched ? 'measured' : 'not measured';
    tile.appendChild(badge);

    tile.addEventListener('click', () => showCardDetail(card));
    return tile;
}

// The detail pane shows one card, with its three parts kept apart:
// what the device advertises, what we measured, and what we have
// noticed. The distance between the first two is the whole point.
function showCardDetail(card) {
    for (const tile of els.cardGrid.querySelectorAll('.card-tile')) {
        tile.classList.toggle('current', tile.dataset.model === card.model_id);
    }
    loadModelCard(card.model_id);
}

function wireCardFilters() {
    for (const control of [els.cardSearch, els.cardFilterArtifact,
                           els.cardFilterMeasured]) {
        control.addEventListener('input', renderCardGrid);
        control.addEventListener('change', renderCardGrid);
    }
}

// -- the references -------------------------------------------------------

// Phase N fills this. The panel exists now so the tab strip is the
// shape the work will land in, rather than a shape it has to be
// reshaped into later.
async function loadReferences() {
    const data = await apiGet('/v1/references');
    els.referenceGrid.innerHTML = '';
    const references = (data && data.references) || [];
    if (!references.length) {
        const empty = document.createElement('p');
        empty.className = 'card-empty';
        empty.textContent = 'No references yet. Make an image you like, '
            + 'then save it as a reference.';
        els.referenceGrid.appendChild(empty);
        return;
    }
    for (const reference of references) {
        els.referenceGrid.appendChild(referenceTile(reference));
    }
}

function referenceTile(reference) {
    const tile = document.createElement('div');
    tile.className = 'reference-tile';

    const name = document.createElement('p');
    name.className = 'reference-name';
    name.textContent = reference.name || reference.id;
    tile.appendChild(name);

    const facts = document.createElement('p');
    facts.className = 'reference-facts';
    facts.textContent = (reference.model_id || '') + ' · '
        + (reference.size || '');
    tile.appendChild(facts);

    return tile;
}

// -- the plan and the badge ----------------------------------------------

function renderPlan(plan) {
    if (!plan) {
        return;
    }
    const model = plan.model || {};
    els.modelId.textContent = model.id || '—';
    els.modelJustification.textContent = plan.justification || '';
    if (plan.download) {
        const gib = (plan.download.size_bytes / (1024 * 1024 * 1024)).toFixed(1);
        say('This needs ' + plan.download.model + ' (' + gib
            + ' GiB), which is not on the appliance yet. It will be '
            + 'downloaded first — about five minutes.', 'warn');
    }
    loadCard(model.id);
    renderAlternatives(plan.alternatives || [], model.id);
}

// The models the resolver ranked behind its choice, as things the user
// can PICK. The resolver picks one and explains why; a user who knows
// the appliance better than the resolver does has to be able to say so.
function renderAlternatives(alternatives, currentId) {
    const box = els.modelAlternatives;
    box.innerHTML = '';
    if (!alternatives.length) {
        return;
    }
    const label = document.createElement('div');
    label.className = 'alt-label';
    label.textContent = 'or use another model';
    box.appendChild(label);
    for (const alternative of alternatives) {
        const button = document.createElement('button');
        const onDevice = alternative.downloaded ? '' : ', not on the device';
        button.className = 'alt'
            + (alternative.id === currentId ? ' current' : '');
        button.textContent = alternative.id + '  ('
            + alternative.npu_usage + '%' + onDevice + ')';
        button.addEventListener('click', () => {
            chosenModelId = alternative.id;
            say('The next image will use ' + alternative.id + '.', 'event');
            renderAlternatives(alternatives, alternative.id);
        });
        box.appendChild(button);
    }
}

async function loadCard(modelId) {
    if (!modelId) {
        return;
    }
    // The card says what the model was MEASURED to do on the appliance.
    // The id is a QUERY PARAMETER because every model id has slashes.
    const card = await apiGet('/v1/models/card?model_id='
        + encodeURIComponent(modelId));
    if (!card) {
        els.modelMeasured.textContent = '';
        return;
    }
    const bits = [];
    if (card.artifacts && card.artifacts.length) {
        bits.push(card.artifacts.join(', '));
    }
    if (card.alpha === 'yes') {
        bits.push('transparent background (' + card.transparent_pct + '%)');
    } else if (card.alpha === 'no') {
        bits.push('opaque background');
    }
    if (card.text_rendering === 'best') {
        bits.push('legible text');
    }
    els.modelMeasured.textContent = bits.join(' · ');
}

// -- the event stream ----------------------------------------------------

function watch(jobId) {
    if (stream) {
        stream.close();
    }
    armed = false;
    // ?job_id= is NOT optional. See the note at the top of this file.
    stream = new EventSource(API + '/v1/session/' + SESSION
        + '/events?job_id=' + encodeURIComponent(jobId));
    stream.onmessage = (message) => {
        let event;
        try {
            event = JSON.parse(message.data);
        } catch (error) {
            return;
        }
        handle(event);
    };
    stream.onerror = () => {
        // The stream ends when the job does; the server closes it.
        if (stream) {
            stream.close();
            stream = null;
        }
    };
}

function handle(event) {
    const kind = event.type;
    const data = event.data || {};

    // Only THIS job's events decide anything. An event with no job id
    // (the swap events) is shown, but it is not ours to act on.
    if (data.job_id && data.job_id !== currentJobId) {
        return;
    }

    switch (kind) {
        case 'job.queued':
            // Our own job has arrived. Everything after this belongs
            // to this job until it finishes.
            armed = true;
            break;

        case 'job.started':
            armed = true;
            break;

        case 'plan.ready':
            els.modelId.textContent = data.model || els.modelId.textContent;
            els.modelJustification.textContent = data.justification
                || els.modelJustification.textContent;
            loadCard(data.model);
            break;

        case 'swap.started':
            showBanner('Loading ' + (data.model || 'the model')
                + ' into the NPU pool', 'swap');
            break;

        case 'swap.finished':
            hideBanner();
            break;

        case 'download.started': {
            const gib = ((data.size_bytes || 0) / (1024 * 1024 * 1024)).toFixed(1);
            showBanner('Downloading ' + (data.model || 'the model') + ' ('
                + gib + ' GiB) — about five minutes', 'download');
            break;
        }

        case 'download.progress':
            showBanner('Downloading the model — ' + Math.round(data.progress || 0)
                + '%', 'download');
            break;

        case 'download.finished':
            hideBanner();
            break;

        case 'generate.started':
            // No job id on this event: only trust it once our own job
            // has been seen starting.
            if (armed) {
                say('Generating with ' + data.model + '…', 'event');
            }
            break;

        case 'generate.finished':
            if (armed) {
                say('Generated.', 'event');
            }
            break;

        case 'critique.ready':
            // The VERDICT, not the fact of a comparison. "The judge
            // compared the image against the requirements" is true of a
            // pass, a fail, and a judge that was never called - it tells
            // the user nothing they can act on.
            if (armed) {
                say(describeVerdict(data), 'event');
            }
            break;

        case 'model.changed':
            // The judge failed twice, so the job moved to another model.
            if (armed) {
                say('The judge was not satisfied, so this is being tried '
                    + 'with ' + (data.to || 'another model') + ' instead.',
                    'event');
            }
            break;

        case 'asset.ready':
            showAsset(data.asset_id, data.path);
            break;

        case 'job.finished':
            hideBanner();
            break;

        case 'job.failed':
            hideBanner();
            say('The job failed: ' + (data.error || 'no reason given'), 'bad');
            break;

        default:
            break;
    }
}

// -- the asset -----------------------------------------------------------

async function showAsset(assetId, path) {
    currentAssetId = assetId;
    // The PNG is fetched as bytes and shown DIRECTLY. Re-encoding it
    // through a canvas is exactly where a transparent background quietly
    // becomes an opaque one, and the alpha channel is the product.
    els.image.src = API + '/v1/assets/' + encodeURIComponent(assetId);
    els.image.onload = () => {
        els.image.classList.remove('hidden');
        els.placeholder.classList.add('hidden');
    };
    els.image.onerror = () => {
        els.placeholder.textContent = 'The image could not be loaded.';
        els.placeholder.classList.remove('hidden');
    };

    const lineage = await apiGet('/v1/assets/' + encodeURIComponent(assetId)
        + '/lineage');
    if (lineage) {
        renderLineage(lineage);
        // The asset's own model, not whatever the last plan chose.
        if (lineage.model_id) {
            els.modelId.textContent = lineage.model_id;
            loadCard(lineage.model_id);
        }
    }
    // WHERE THE FILE IS. The user must be able to find the PNG without
    // asking, and the lineage is where the path is recorded.
    const filePath = path || (lineage && lineage.path) || '';
    if (filePath) {
        els.filePath.textContent = filePath;
        els.filePath.classList.remove('hidden');
    }
    addThumb(assetId);
}

function renderLineage(lineage) {
    const lines = [];
    lines.push('request    : ' + (lineage.request || ''));
    lines.push('model      : ' + (lineage.model_id || ''));
    lines.push('size       : ' + (lineage.size || ''));
    lines.push('attempts   : ' + (lineage.attempts === undefined
        ? '—' : lineage.attempts));
    if (lineage.requirements) {
        // Skip the fields that say nothing: a "none", a "no", a "general",
        // an empty string, or an empty list.
        const wanted = Object.entries(lineage.requirements)
            .filter(([, value]) => {
                if (value === null || value === undefined) {
                    return false;
                }
                if (Array.isArray(value)) {
                    return value.length > 0;
                }
                const text = String(value).trim().toLowerCase();
                return text !== '' && text !== 'none' && text !== 'no'
                    && text !== 'general' && text !== 'null';
            })
            .map(([key, value]) => key + '='
                + (Array.isArray(value) ? value.join(', ') : value));
        lines.push('requirements: ' + (wanted.join(', ') || '—'));
    }
    if (lineage.critique) {
        const critique = lineage.critique;
        lines.push('critique   : ' + (critique.passed ? 'pass'
            : critique.inconclusive ? 'inconclusive' : 'fail'));
        if (critique.reasons && critique.reasons.length) {
            lines.push('             ' + critique.reasons.join(' '));
        }
    } else if (lineage.critique_skipped_reason) {
        lines.push('critique   : skipped — ' + lineage.critique_skipped_reason);
    }
    if (lineage.prompt) {
        lines.push('prompt     : ' + lineage.prompt.replace(/\s+/g, ' ').trim());
    }
    els.lineage.textContent = lines.join('\n');
}

function addThumb(assetId) {
    const thumb = document.createElement('button');
    thumb.className = 'thumb';
    thumb.title = assetId;
    const image = document.createElement('img');
    image.src = API + '/v1/assets/' + encodeURIComponent(assetId);
    image.alt = assetId;
    thumb.appendChild(image);
    thumb.addEventListener('click', () => {
        currentAssetId = assetId;
        showAsset(assetId);
    });
    els.thumbs.insertBefore(thumb, els.thumbs.firstChild);
}

// -- the banner ----------------------------------------------------------

function showBanner(text, kind) {
    els.bannerText.textContent = text;
    els.banner.classList.add('active');
    els.banner.classList.toggle('download', kind === 'download');
    if (bannerStartedAt === null) {
        bannerStartedAt = Date.now();
    }
    tick();
    if (bannerTimer === null) {
        bannerTimer = setInterval(tick, 1000);
    }
}

function tick() {
    if (bannerStartedAt === null) {
        return;
    }
    const seconds = Math.floor((Date.now() - bannerStartedAt) / 1000);
    const minutes = Math.floor(seconds / 60);
    els.bannerTime.textContent = String(minutes).padStart(2, '0') + ':'
        + String(seconds % 60).padStart(2, '0');
}

function hideBanner() {
    els.banner.classList.remove('active');
    els.banner.classList.remove('download');
    bannerStartedAt = null;
    if (bannerTimer !== null) {
        clearInterval(bannerTimer);
        bannerTimer = null;
    }
}

// -- the NPU meter -------------------------------------------------------

async function updateNpu() {
    const npu = await apiGet('/v1/npu');
    if (!npu) {
        return;
    }
    const used = npu.used_pct || 0;
    els.npuFill.style.width = used + '%';
    els.npuText.textContent = used + '% used';
    const resident = npu.resident || [];
    els.npuResident.textContent = resident.length
        ? resident.join(', ')
        : 'nothing resident';
    els.npuResident.title = resident.join('\n');
}

// -- what the judge said ---------------------------------------------------
//
// The judge's verdict is the one piece of feedback a user can act on.
// It arrives as a verdict, some reasons, and the changes the judge
// wants. Written out, because "the judge compared the image against the
// requirements" is true whether it passed, failed, or never ran.

function describeVerdict(data) {
    const reasons = data.reasons || [];
    const changes = data.suggested_changes || [];
    if (data.passed) {
        const why = reasons.length ? ' ' + reasons[0] : '';
        return 'The judge passed it.' + why;
    }
    if (data.inconclusive) {
        return 'The judge could not decide' + (reasons.length
            ? ': ' + reasons[0] : '') + '.';
    }
    if (changes.length) {
        return 'The judge asked for: ' + changes.join('; ') + '.';
    }
    return 'The judge was not satisfied' + (reasons.length
        ? ': ' + reasons[0] : '') + '.';
}

// -- who talks, and who judges ---------------------------------------------
//
// The guide is the agency's own catalogue, not a hard-coded list here.
// A model that can SEE the image judges the picture; one that cannot
// judges only the prompt, and cannot catch a generation that simply
// came out wrong. So the picker says which is which, and the cost.

async function loadRoles() {
    const data = await apiGet('/v1/roles');
    if (!data) {
        return;
    }
    fillRoleSelect(els.roleConversation, data.models || [], data.conversation);
    // The critic MUST be a model that can see the image. The API
    // already sends the vision-capable subset separately, so the
    // dropdown is built from that and nothing else - offering a
    // text-only judge here would be offering a judge that cannot
    // judge.
    fillRoleSelect(els.roleCritic, data.vision_models || [], data.critic);
    renderRoleNote(data);
}

function fillRoleSelect(select, models, current) {
    select.innerHTML = '';
    for (const model of models) {
        const option = document.createElement('option');
        option.value = model.id;
        const marks = [];
        if (model.vision) {
            marks.push('sees');
        }
        marks.push(model.npu_usage + '%');
        if (!model.downloaded) {
            marks.push('not on the device');
        }
        option.textContent = model.id + '  (' + marks.join(', ') + ')';
        select.appendChild(option);
    }
    if (current && current.model) {
        select.value = current.model;
    }
}

function renderRoleNote(data) {
    const critic = data.critic || {};
    const note = els.roleNote;
    const fit = data.fit || {};
    let text;
    if (critic.vision) {
        note.classList.add('sees');
        text = 'The judge can SEE the image, so it judges the picture '
            + 'and not just the prompt. ';
    } else {
        note.classList.remove('sees');
        text = 'The judge reads text only, so it judges the PROMPT. '
            + 'It cannot see what was generated. ';
    }
    if (fit.total) {
        // The talker is NOT part of this sum: it has already written the
        // scene description by the time the image is made, so its
        // weights are swapped out and it does not compete for the pool.
        text += fit.fits
            ? `While judging: ${fit.critic_npu}% judging + `
              + `${fit.generator_npu}% generating = ${fit.total}% of the pool.`
            : `It does not fit: ${fit.critic_npu}% judging + `
              + `${fit.generator_npu}% generating = ${fit.total}%, over the `
              + `${fit.ceiling}% ceiling.`;
        if (!fit.fits && fit.advice) {
            text += ' ' + fit.advice;
        }
    }
    note.textContent = text;
}

async function setRole(which) {
    const select = which === 'conversation'
        ? els.roleConversation : els.roleCritic;
    const body = {};
    body[which] = select.value;
    try {
        const data = await apiPost('/v1/roles', body);
        renderRoleNote(data);
        if (data.note) {
            say(data.note, 'event');
        }
    } catch (error) {
        say('The role could not be changed: ' + error.message, 'bad');
    }
}

// -- the start -----------------------------------------------------------

els.composer.addEventListener('submit', submit);
els.feedbackForm.addEventListener('submit', revise);
els.roleConversation.addEventListener('change', () => setRole('conversation'));
els.roleCritic.addEventListener('change', () => setRole('critic'));

// THE DROP ZONE. A drag anywhere on it, or a click to choose a file.
els.dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    els.dropzone.classList.add('dragging');
});
els.dropzone.addEventListener('dragleave', () => {
    els.dropzone.classList.remove('dragging');
});
els.dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    els.dropzone.classList.remove('dragging');
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length) {
        uploadSource(files[0]);
    }
});
els.dropzone.addEventListener('click', (event) => {
    // The button inside the source panel clears it; it must not open
    // the file picker as well.
    if (event.target.closest('#source-clear')) {
        return;
    }
    els.fileInput.click();
});
els.fileInput.addEventListener('change', () => {
    if (els.fileInput.files && els.fileInput.files.length) {
        uploadSource(els.fileInput.files[0]);
    }
    els.fileInput.value = '';
});
els.sourceClear.addEventListener('click', (event) => {
    event.stopPropagation();
    clearSource();
});

// THE MODEL CARDS. The Models tab fetches its cards the first time it
// is opened, and the filters re-render the grid from what it already
// has — a keystroke must not be a request.
wireTabs();
wireCardFilters();
TAB_LOADERS.models = {run: loadAllCards};
TAB_LOADERS.references = {run: loadReferences};

// THE DIALOG. The user approves the model before anything is spent.
els.dialogCancel.addEventListener('click', () => {
    els.dialogBackdrop.hidden = true;
    say('Cancelled.', 'event');
});
els.dialogGo.addEventListener('click', () => {
    const request = lastRequest;
    els.dialogBackdrop.hidden = true;
    startGeneration(request, chosenModelId);
});
els.dialogBackdrop.addEventListener('click', (event) => {
    // A click on the backdrop is a click outside the dialog.
    if (event.target === els.dialogBackdrop) {
        els.dialogBackdrop.hidden = true;
    }
});

loadRoles();

updateNpu();
setInterval(updateNpu, 3000);

say('Ready. Describe the image you want.', 'event');
