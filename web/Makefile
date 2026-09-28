.PHONY: test demo
test:
	node --test tests/*.test.mjs
	cd .. && PYTHONPATH=src python3 -m unittest discover -s web/tests -p 'test_*.py' -v
demo:
	python3 demo.py
