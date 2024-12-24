# -*- coding: utf-8 -*-
import os
import asyncio
import traceback
import shutil
import tempfile
import mimetypes
from lib_msa import MSAAsyncShell, log_handlers
import subprocess
import time
import logging
import sys
from PyPDF2 import PdfFileWriter, PdfFileReader
import pathlib
from pathlib import Path
import base64
from base64 import decodestring
import chardet
import numpy as np
from pdf2image import convert_from_path, convert_from_bytes
from pdfrw import PdfReader, PdfWriter
import sys
import re
import concurrent.futures

max_pages_short = int(os.getenv('MAX_PAGES_SHORT', 1))
max_pages_full = int(os.getenv('MAX_PAGES_FULL', 1))
recognition_type = 'full'
LIBREOFFICE_PROCESS_CALL_TIMEOUT = 600
# не стал выносить в переменную окружения, потому что менять это значение не следует
# в крайнем случае, можно править руками внутри контейнера

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

pool = concurrent.futures.ProcessPoolExecutor()

app = MSAAsyncShell(
    service_name="document-reader",
    rabbitmq_url=os.getenv("RABBIT_URL"),
    max_tasks_count=1, # только 1: конвертилка сходит с ума при параллельной работе (баг давно известен и не лечится)
    ack_task_before=True
)

def get_num_pages(input_pdf_path, recognition_type):
    result = 'good'
    try:
        with open(input_pdf_path, "rb") as f:
            input_file = PdfFileReader(f, strict=False)

            if recognition_type == 'full':
                if input_file.getNumPages() > max_pages_full:
                    result = f'The number of pages in full pipeline is more than {max_pages_full}'
            else:
                if input_file.getNumPages() > max_pages_short:
                    result = f'The number of pages in short pipeline is more than {max_pages_short}'
    except:
        result = 'Failed to count the number of pages'
    
    return result

def page_counter(tmp_path):
    script = f'exiftool -"Pages" {tmp_path}/*.docx'
    result = subprocess.run(script, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        pages = int(re.findall(r'\d+',result.stdout.decode("utf-8"))[0])
        logger.info(f'pages in document {pages}')
        return(pages)
    except:
        return {'error': 'cant count the number of pages'}

def first_page(tmp_path):
    pdf = PdfFileReader(open(tmp_path, "rb"))
    pdf_writer = PdfFileWriter()
    if pdf.getNumPages() > 2:
        first_page = pdf.getPage(0)
        second_page = pdf.getPage(1)
        pdf_writer.addPage(first_page)
        pdf_writer.addPage(second_page)

        tmp_path = tmp_path.replace('input1','input')
        with Path(tmp_path).open(mode="wb") as output_file:
            pdf_writer.write(output_file)
    else:
        tmp_path = tmp_path.replace('input1','input')
        pdf_writer.cloneReaderDocumentRoot(pdf)
        with Path(tmp_path).open(mode="wb") as output_file:
            pdf_writer.write(output_file)

def decoder(b):
    s = ''
    for i in range(len(b)):
        enc = chardet.detect(b[i:i+1])['encoding']
        if enc is not None:
            s += b[i:i+1].decode(enc)
    return s

def if_valid(path):
    script = f'exiftool -a {path}'
    result = subprocess.run(script, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = decoder(result.stdout).lower()  # MacCyrillic
    logger.info(f'result decoded  >>>>>>>>>>>>> {result}')
    x = result.split('error')
    if len(x) == 1:
        logger.info(f'>>>>>>> True')
        return True, 'empty message'
    else:
        logger.info(f'>>>>>>> False')
        message = x[1].replace(':', '')
        return False, message.strip()
        logger.info(f'message >>>>>>> {message}')

def sk_read_page_pdf_file(path: pathlib.Path) -> np.array:
    # hack to rewrite some unreadable documents and thus make them readable
    with tempfile.NamedTemporaryFile(suffix='.pdf',prefix=os.path.basename(__file__)) as fp:
        logger.info(os.path.basename(__file__))
        filepath = os.path.dirname(fp.name)
        trailer = PdfReader(path)     
        root = trailer['/Root']['/Pages']['/Kids'][0]
        while root['/Type'] != '/Page':
            root = root['/Kids'][0]
        PdfWriter(fp.name).addpage(root).write()
        pages = convert_from_path(fp.name, 228, last_page=1)
    picture = np.array(pages[0].getdata()).reshape(*pages[0].size[::-1], 3).astype(np.uint8)
    return picture

def sk_crop(input_pdf_path):
    fp_image = sk_read_page_pdf_file(pathlib.Path(input_pdf_path))

    return {
        "result": {
            "image": fp_image.ravel().tobytes(), #open(input_pdf_path, 'rb').read()
            "shape": list(fp_image.shape)
        }
    }

@app.callback()
async def parse_docs(document_data: bytes, recognition_type=recognition_type, data_type = 'not_sk'):
    tmp_path = tempfile.mkdtemp()
    doc_5bytes = document_data[1:4] # тут хранится метадата
    try:
        if doc_5bytes != b"PDF":
            # сохраняем в предположении, что пришёл doc/docx/rtf
            input_path = os.path.join(tmp_path, "input.docx")
            with open(input_path, "wb") as f:
                f.write(document_data)
            allowed_formats = [
                'application/msword',
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/zip',
                'text/rtf',
                'text/html',
                'application/octet-stream',
                'text/plain',
            ]
            logger.info(f'********* MimeTypes **********')
            format_ = mimetypes.MimeTypes().guess_type(input_path)[0].lower()
            
            logger.info(f'********* {format_} **********')
            
            if format_ not in allowed_formats:
                return {'error': f'Document format {format_} not supported. Allowed formats: {allowed_formats}'}
            if 'pdf' not in format_:
                #если это не pdf, конвертим, сохраняем как input.pdf
                status, corrupted_msg = if_valid(input_path)
                if not status:
                    logging.info(f"error: Document corrupted. Traceback: {corrupted_msg}")
                    return {"error": f"Document corrupted. Traceback: {corrupted_msg}"}
                
                logger.info('********* начали конвертить **********')
                
                pages = page_counter(tmp_path) #TODO обсудить возможность ветвления, если не смогли распознать кол-во страниц
                try:
                    if recognition_type == 'full':
                        if pages > max_pages_full:
                            return {'error': f'The number of pages in full pipeline is more than {max_pages_full}'}
                    else:
                        if pages > max_pages_short:
                            return {'error': f'The number of pages in short pipeline is more than {max_pages_short}'}
                except:
                    pass
                    
                cmd = f"bash -c 'cd {tmp_path} ; libreoffice --headless --convert-to pdf input.docx'"
                process = await asyncio.create_subprocess_shell(cmd)
                try:
                    await asyncio.wait_for(process.wait(), LIBREOFFICE_PROCESS_CALL_TIMEOUT)
                    
                    logger.info('********* закончили конвертить **********')
                    
                except Exception as e:
                    # таймаут на вызов libreoffice: всё плохо, перезапускаем контейнер и пишем в лог
                    logging.exception(f"""
                        error': {e}
                        traceback: {''.join(traceback.format_tb(e.__traceback__))}
                    """)
                    sys.exit(1) # выходим, чтобы докер перезапустил контейнер
            else:
                # если это pdf, переименовываем в input.pdf
                input_pdf_path = os.path.join(tmp_path, "input.pdf") #input1
                await app.exec_shell_cmd(f'''mv {input_path} {input_pdf_path}''')
                
                #first_page(input_pdf_path)
                
                if data_type == 'sk':    # после проверки миметайпс на пдф
                    return sk_crop(input_pdf_path)
                        
        else:
            logger.info('********* ушли в ветку пдф **********')
            # если это pdf, переименовываем в input.pdf
            input_pdf_path = os.path.join(tmp_path, "input.pdf") #input1
            with open(input_pdf_path, "wb") as f:
                f.write(document_data)
                
            #first_page(input_pdf_path)
            
            if data_type == 'sk':   # после проверки 5 байтами на пдф
                return sk_crop(input_pdf_path)
            logger.info('start pdf reader')

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(pool, get_num_pages, input_pdf_path, recognition_type)
            if result != 'good':
                return {'erorr': f'{result}'}
            
        logger.info('end pdf reader')
        if data_type == 'sk':              #после конверта всех типов в пдф
            return sk_crop(os.path.join(tmp_path, "input.pdf"))
        logger.info("start convert script")
        
        # convert_script = [
        #     f"cd {tmp_path}",
        #     "if [[ $(pdfimages -list input.pdf | grep image | wc -l) -gt 0 ]]",
        #     "then pdftoppm -r 200 input.pdf -jpeg image",
        #     "else pdftotext -enc UTF-8 -raw input.pdf data.txt",
        #     "fi"
        # ]
        
        # await app.exec_shell_cmd("bash -c '{}'".format(" ; ".join(convert_script)))
        convert_script_txt = 'pdftotext -enc UTF-8 -raw input.pdf data.txt'

        test_string = f'cd {tmp_path} ; pdfimages -list input.pdf | grep image | wc -l'
        image_count = await app.call_shell_cmd(f"bash -c '{test_string}'")
        logger.info('количество страниц')
        logger.info(image_count)

        if re.findall('\d', image_count.decode("utf-8"))[0] != '0':
            i=0
            while True:
                i+=1
                convert_script_image = f'timeout 10s  pdftoppm -f {i} -l {i} -r 200 input.pdf -jpeg image'
                EC = await app.exec_shell_cmd(f"bash -c 'cd {tmp_path} ; {convert_script_image}'")
                logger.info(i)
                logger.info(EC)
                if EC == 0:
                    pass
                elif EC == 124:
                    ## подставляем картинку
                    pass
                elif EC == 99:
                    break
        else:
            await app.exec_shell_cmd(f"bash -c 'cd {tmp_path} ; {convert_script_txt}'")

        logger.info("end convert script")
        logger.info("start files")
        files = [
            open(os.path.join(tmp_path, file), "rt", encoding='utf-8').read() for file in os.listdir(tmp_path) if file.endswith((".txt"))
        ]
        files.extend(
            open(os.path.join(tmp_path, file), "rb").read() for file in os.listdir(tmp_path) if file.endswith((".jpg"))
        )
        logger.info("end files")
        if len(files) == 0:
            logger.info('ошибка при конвертации инпут.пдф в тхт или джпег')
            return {'error': f'convert error'}
        # try:
        #     logger.info('**********ушли в рееспонс тайп**********')
        #     check_file_type = ''.join(files)
        #     if check_file_type.endswith(".jpg"):
        #         logger.info('********* картинка *************')
        #     else:
        #         # logger.info(f'********* не картинка ************ {str(check_file_type)}')
        #         logger.info(f'********* не картинка ************')

        response_type = "texts" if any(isinstance(file, str) for file in files) else "images"
        # logger.info('response_type', response_type)
        return {
            "result": {
                "type": response_type,
                response_type: files
            }
        }
        # except:
        #     logger.info('*************ушли в ексепт при попытке выполнить респонс тайп*************')
        #     return {'error': f'error in response_type'}

    except UnicodeDecodeError as u_ex:
        return {'error': f'Error reading metadata'}
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)

if __name__ == "__main__":
    app.register_log_handler(
        log_handlers.get_elasticsearch_log_handler(
            es_url=os.getenv('ES_URL'),
            name=app.service_name
        )
    )
    app.run()
