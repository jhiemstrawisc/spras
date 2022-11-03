import pytest
import shutil
from pathlib import Path
from src.mincostflow import MinCostFlow

TEST_DIR = 'test/MinCostFlow/'
OUT_FILE = TEST_DIR+'output/mincostflow-output.txt'

class TestMinCostFlow:

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_required(self, graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)

        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE)
        assert out_path.exists()
        #TODO: assert for the output .equals expexcted_output 

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_missing_capacity(self, graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)

        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE,
            flow=1)
        assert out_path.exists()

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_missing_flow(self, graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)

        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE,
            capacity=1)
        assert out_path.exists()

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_too_much_flow(self,graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)

        with pytest.raises(RuntimeError):
            MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
                targets=TEST_DIR + 'input/' + graph + '/targets.txt',
                edges=TEST_DIR + 'input/' + graph + '/edges.txt',
                output_file=OUT_FILE,
                flow=50,
                capacity=1)
        

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_no_flow(self,graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)

        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE,
            flow=0,
            capacity=1)
        assert out_path.exists()

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_all_optional(self, graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)
        # Include all optional arguments
        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE,
            flow=1,
            capacity=1,
            singularity=False)
        assert out_path.exists()

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    def test_mincostflow_missing(self, graph):
        # Test the expected error is raised when required arguments are missing
        with pytest.raises(ValueError):
            MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
                targets=TEST_DIR + 'input/' + graph + '/targets.txt',
                output_file=OUT_FILE)

    @pytest.mark.parametrize('graph',['graph1', 'graph2','graph3','graph4'])
    @pytest.mark.skipif(not shutil.which('singularity'), reason='Singularity not found on system')
    def test_mincostflow_singularity(self, graph):
        out_path = Path(OUT_FILE)
        out_path.unlink(missing_ok=True)
        # Include all optional arguments
        MinCostFlow.run(sources=TEST_DIR + 'input/' + graph +'/sources.txt',
            targets=TEST_DIR + 'input/' + graph + '/targets.txt',
            edges=TEST_DIR + 'input/' + graph + '/edges.txt',
            output_file=OUT_FILE,
            flow=1,
            capacity=1,
            singularity=True)
        assert out_path.exists()