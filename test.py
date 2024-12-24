import pytest
from app import page_counter, first_page, if_valid
import os

def test_page_counter():
    a = page_counter('./')
    assert a == 3
    
def test_first_page():
    first_page('input1.pdf')
    assert os.path.isfile('input.pdf') == True

def test_if_valid():
    status, corrupted_msg = if_valid('input1.docx')
    assert status == True
    assert corrupted_msg == 'empty message'

if __name__ == '__main__':
    pytest.main(['test.py'])
