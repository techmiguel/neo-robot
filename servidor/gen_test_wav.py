from src.tts.synthesizer import synthesize, pcm_a_wav
pcm = synthesize("¿Cuántos planetas tiene el sistema solar?")
open("tests/fixtures/pregunta_test.wav", "wb").write(pcm_a_wav(pcm))
print("WAV generado: tests/fixtures/pregunta_test.wav")
