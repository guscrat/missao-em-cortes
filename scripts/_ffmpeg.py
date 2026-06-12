"""Formato canônico do pipeline, compartilhado pelos steps 4/4b/5/6.

1280x720, 30fps, yuv420p, H.264 via NVENC (GPU), AAC 44100 Hz stereo.
Com todos os segmentos nesse formato, o 06_montar concatena com -c copy
(instantâneo) em vez de re-encodar o vídeo inteiro.

Pra rodar numa máquina SEM NVENC (CPU), troque o VENC por:
    VENC = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
"""
VENC = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23",
        "-b:v", "0", "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
SCALE_PAD = ("scale=1280:720:force_original_aspect_ratio=decrease,"
             "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")
