if (!ReadableStream.prototype[Symbol.asyncIterator]) {
	ReadableStream.prototype[Symbol.asyncIterator] = ReadableStream.prototype.getIterator = async function* (){
		const reader = this.getReader();
		let done, value;
		while (true) {
			({ value, done } = await reader.read());
			if (done) {
				return;
			}
			yield value;
		}
	};
}

async function* streamLines(readableStream) {
	let decoder = new TextDecoder();
	for await (let chunk of readableStream) {
		for (let line of decoder.decode(chunk).split('\n')) {
			yield line;
		}
	}
}
