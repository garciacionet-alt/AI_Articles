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
};

// The model the user chose, if any. Empty means "the resolver decides".
// It survives between requests: choosing a model is a standing
// preference, not a one-off.
let chosenModelId = '';

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

    try {
        // Plan first: it costs one planner call and it tells the user
        // which model, whether a swap is coming, and whether a DOWNLOAD
        // is coming — before any of that starts.
        const plan = await apiPost('/v1/plan', {request, model_id: chosenModelId});
        renderPlan(plan);
    } catch (error) {
        say('The plan failed: ' + error.message, 'bad');
        return;
    }

    try {
        const queued = await apiPost('/v1/generate', {request, model_id: chosenModelId});
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
            showAsset(data.asset_id);
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

async function showAsset(assetId) {
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
    fillRoleSelect(els.roleConversation, data, data.conversation);
    fillRoleSelect(els.roleCritic, data, data.critic);
    renderRoleNote(data);
}

function fillRoleSelect(select, data, current) {
    select.innerHTML = '';
    const models = data.models || [];
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

loadRoles();

updateNpu();
setInterval(updateNpu, 3000);

say('Ready. Describe the image you want.', 'event');
