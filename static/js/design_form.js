let formEl = document.forms[0];
let formData = new FormData(formEl);
let submitEl = document.querySelector('button');
let submitElSpinner = submitEl.querySelector('.spinner-border');
let resultsEl = document.getElementById('results');
let resultsListEl = resultsEl.querySelector('ul');

const clearError = () => {
	let priorErrEl = document.querySelector('.bg-danger');
	if (priorErrEl) {
		priorErrEl.remove();
	}
}

const setError = err => {
	clearError();
	submitEl.removeAttribute('disabled');
	submitElSpinner.remove();
	let errEl = document.createElement('p');
	errEl.classList.add('bg-danger');
	errEl.innerText = err.error;
	if (err.error_code !== undefined) {
		errEl.innerText += ` (error code: ${err.error_code})`;
	}
	resultsEl.appendChild(errEl);
}

const enableForm = () => {
	submitEl.removeAttribute('disabled');
	submitElSpinner.classList.add('hidden');
}

formEl.addEventListener('submit', (e) => {
	clearError();

	resultsEl.classList.remove('hidden');
	resultsEl.removeAttribute('aria-hidden');
	submitEl.setAttribute('disabled', '');
	submitElSpinner.classList.remove('hidden');

	const maybeError = row => {
		if (row.startsWith('error: ')) {
			return JSON.parse(row.substr('error: '.length));
		}
		return null;
	}

	(async () => {
		let resp = await fetch('/api/v0/images', {
			method: 'POST',
			body: formData,
		});
		let it = streamLines(resp.body);
		let err;
		let firstRow = (await it.next()).value;
		if ((err = maybeError(firstRow)) !== null) {
			setError(err);
			return;
		}
		let imageId = firstRow;
		for await (let line of it) {
			if (!line) { continue; }
			console.log(line);
			if ((err = maybeError(line)) !== null) {
				setError(err);
				enableForm();
				return;
			}

			let [wasQuantized, designCode] = line.split(',');
			let row = document.createElement('li');
			if (parseInt(wasQuantized)) {
				let emojiSpan = document.createElement('span');
				emojiSpan.classList.add('emoji');
				emojiSpan.innerText = '⚠️';
				emojiSpan.title = quantizedMessage;
				row.appendChild(emojiSpan);
			}

			row.appendChild(document.createTextNode(' MA-' + designCode));
			resultsListEl.appendChild(row);
		}

		let doneEl = document.createElement('div');
		// i know innerHtml is bad but otherwise this would be so tedious
		doneEl.innerHTML = `
			<h2>Done</h2>
			<p>
				<span class=emoji>✅</span>️ <a href="/image/${imageId}">View your created design</a>
			</p>
		`;
		resultsEl.appendChild(doneEl);
		submitElSpinner.classList.add('hidden');
	})();
	// do this last so that if anything fails along the way (e.g. on an old browser) the
	// normal submit form still works
	e.preventDefault();
});
