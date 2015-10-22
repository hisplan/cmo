from collections import defaultdict
import json, subprocess, sys, re, magic
#STRAWMAN FIXME
#THIS WOULD BE A PROGRAMMATICALLY INGESTED JSON ON MODULE LOAD IN REAL LIFE
#DONT HATE THIS PART
#programs = defaultdict(dict)
#programs['bwa']={"default":"/opt/common/CentOS_6/bwa/bwa-0.7.12/bwa",
#                 "0.7.12":"/opt/common/CentOS_6/bwa/bwa-0.7.12/bwa",
#                 "0.7.10":"/opt/common/CentOS_6/bwa/bwa-0.7.10/bwa"
#                 }
#programs['samtools']={"default":"/opt/common/CentOS_6/samtools/samtools-0.1.19/samtools",
#                      "0.1.19":"/opt/common/CentOS_6/samtools/samtools-0.1.19/samtools"}
#genomes = defaultdict(dict)
#genomes['hg19']={"fasta":"/ifs/depot/assemblies/H.sapiens/hg19/hg19.fasta"}
json_config = json.load(open("/opt/common/CentOS_6-dev/cmo/cmo_resources.json"))
programs = json_config['programs']
genomes = json_config['genomes']
chr1_fingerprints = json_config['chr1_fingerprints']

def infer_fasta_from_bam(bam_file):
    get_chr1_cmd= [programs['samtools']['default'], "view -H", bam_file, "| fgrep \"@SQ\" | awk '{print $2,$3}'"]
    chr_tags = subprocess.Popen(" ".join(get_chr1_cmd), shell=True, stdout=subprocess.PIPE, stderr=open("/dev/null")).communicate()[0]
    chr_name = None
    length = None
    for line in chr_tags.split("\n"):
        if not line:
            break
        (this_chr, this_length) = line.split(" ")
        if re.search("SN:(chr)?1$", this_chr)!=None:
            chr_name = this_chr[3:]
            length = this_length[3:]
    if chr_name == None:
        #we didn't find a match
        return(None, None)
    for candidate in chr1_fingerprints:
        if chr1_fingerprints[candidate]['name']==chr_name and chr1_fingerprints[candidate]['length']==int(length):
            print >>sys.stderr, "Inferred genome to be %s" % candidate
            return (candidate, genomes[candidate]['fasta'])
    print >>sys.stderr, "Chromosome 1 name %s, length %s, doesn't match any standard refs?" % (chr_name, length)
    return (None, None)

def infer_sample_from_bam(bam_file):
    get_rg_cmd= [programs['samtools']['default'], "view -H", bam_file, "| grep \"^@RG\" "]
    rg_lines = subprocess.Popen(" ".join(get_rg_cmd), shell=True, stdout=subprocess.PIPE, stderr=open("/dev/null")).communicate()[0]
    sample_dict = {}
    for rg in rg_lines.splitlines():
        tags = rg.split("\t")
        for tag in tags:
            if tag[0:2]=="SM":
                sample_dict[tag[3:]]=1
    if len(sample_dict.keys()) > 1:
                    print >>sys.stderr, "Mixed sample tags in Read Group header for %, can't infer a single sample name from this bam naively" % bam_file
    elif len(sample_dict.keys()) == 1:
        print >>sys.stderr, "Found one sample key for this bam: %s" % sample_dict.keys()[0]
        return sample_dict.keys()[0]
    else:
        #we didnt find any RG with SM: at all :(
        print >>sys.stderr, "No @RG lines with SM: tags found in %s, can't infer sample" % bam_file
    return None

def filesafe_string(string):
    keepcharacters = ('.','_')
    return  "".join(c for c in string if c.isalnum() or c in keepcharacters).rstrip()


def call_cmd(cmd, shell=True, stderr=None, stdout=None, stdin=None):
    if stdout and not hasattr(stdout, "write"):
        stdout=open(stdout, "w")
    if stderr and not hasattr(stderr, "write"):
        stderr=open(stderr, "w")
    if stdin and not hasattr(stdin, "read"):
        stdin=open(stdin, "r")
    try:
        return_code = subprocess.check_call(cmd, shell=shell, stderr=stderr, stdout=stdout, stdin=stdin)
    except subprocess.CalledProcessError, e:
        print >>sys.stderr, "Non Zero Exit Code %s from %s" % (e.returncode, cmd)
        print >>sys.stderr, "Bailing out!"
        sys.exit(1)
    except IOError, e:
        print >>sys.stderr, e
        print >>sys.stderr, "I/O error({0}): {1}".format(e.errno, e.strerror)
        sys.exit(1)

logging_options = [
        ("--stderr", "log stderr to file"),
        ("--stdout", "log stdout to file"),
        ]

def add_logging_options(parser):
    for (arg, help) in logging_options:
        parser.add_argument(arg, default=None, help=help)

def remove_logging_options_from_dict(dict):
        for (arg, help) in logging_options:
            key = arg.replace("--","")
            if key in dict:
                del dict[key]


TABIX_LOCATION = '/opt/common/CentOS_6/samtools/samtools-1.2/htslib-1.2.1/tabix'
BGZIP_LOCATION = '/opt/common/CentOS_6/samtools/samtools-1.2/htslib-1.2.1/bgzip'
SORTBED_LOCATION = '/opt/common/CentOS_6/bedtools/bedtools-2.22.0/bin/sortBed'
#BCFTOOLS_LOCATION = '/opt/common/CentOS_6/bcftools/bcftools-1.2/bin/bcftools'

def sort_vcf(vcf):

    outfile = vcf.replace('.vcf', '.sorted.vcf')
    cmd = [SORTBED_LOCATION, '-i', vcf, '-header']
    print >> sys.stdout, 'sortBed command: %s'%(' '.join(cmd))
    #logger.debug('sortBed command: %s'%(' '.join(cmd)))
    try:
        rv = subprocess.check_call(cmd, stdout=open(outfile,'w'))
        return outfile
    except subprocess.CalledProcessError, e:
        print >> sys.stderr, "Non-zero exit code from sortBed! Bailing out."
        #logger.critical("Non-zero exit code from sortBed! Bailing out.")
        sys.exit(1)

    
def bgzip(vcf):

    if re.search('.gz', vcf):
        return vcf
    outfile = '%s.gz'%(vcf)
    cmd = [BGZIP_LOCATION, '-c', vcf]
    #logger.debug('BGZIP COMMAND: %s'%(' '.join(cmd)))
    print >> sys.stderr, 'BGZIP COMMAND: %s'%(' '.join(cmd))
    subprocess.call(cmd, stdout=open(outfile, 'w'))
    return outfile


def tabix_file(vcf_file):

    ''' index a vcf file with tabix for random access'''
    with magic.Magic(flags=magic.MAGIC_MIME_TYPE) as m:
        if(m.id_filename(vcf_file).find('gz') == -1):
            print >> sys.stderr, 'VCF File needs to be bgzipped for tabix random access. tabix-0.26/bgzip should be compiled for use'
            #logger.critical('VCF File needs to be bgzipped for tabix random access. tabix-0.26/bgzip should be compiled for use')
            sys.exit(1)
    cmd = [TABIX_LOCATION, '-p' , 'vcf', vcf_file]
    print >> sys.stdout, 'Tabix command: %s'%(' '.join(cmd))
    #logger.debug('Tabix command: %s'%(' '.join(cmd)))
    try:
        rv = subprocess.check_call(cmd)
    except subprocess.CalledProcessError, e:
        print >> sys.stderr, 'Non-zero exit code from Tabix! Bailing out.'
        #logger.critical('Non-zero exit code from Tabix! Bailing out.')
        sys.exit(1)


def fix_contig_tag_in_vcf(vcf_file):

    #OK for small files only
    process_one = subprocess.Popen(['bcftools', 'view', '%s'%(vcf_file)], stdout=subprocess.PIPE)
    vcf = re.sub(r'(?P<id>##contig=<ID=[^>]+)', r'\1,length=0', process_one.communicate()[0])
    process_two = subprocess.Popen([BGZIP_LOCATION, '-c'], stdin=subprocess.PIPE, stdout=open(vcf_file,'w'))
    process_two.communicate(input=vcf)


def fix_contig_tag_in_vcf_by_line(vcf_file):

    process_one = subprocess.Popen(['bcftools', 'view', '%s'%(vcf_file)], stdout=subprocess.PIPE)
    process_two = subprocess.Popen([BGZIP_LOCATION, '-c'], stdin=subprocess.PIPE, stdout=open('fixed.vcf','w'))

    with process_one.stdout as p:
        for line in iter(p.readline, ''):
            line = re.sub(r'(?P<id>##contig=<ID=[^>]+)', r'\1,length=0', line)
            process_two.stdin.write('%s\n'%(line))
    process_two.stdin.close()
    process_two.wait()

    cmd = ['mv', 'fixed.vcf', vcf_file]
    subprocess.call(cmd)


def normalize_vcf(vcf_file, ref_fasta, version="default", method='bcf'):
    norm_command = programs[method][version]
    sorted_vcf = sort_vcf(vcf_file)
    zipped_file = bgzip(sorted_vcf)
    tabix_file(zipped_file)
    output_vcf = zipped_file.replace('.vcf', '.normalized.vcf')
    cmd = ''
    if method == 'vt':
        cmd = [norm_command, 'normalize', '-r', ref_fasta, zipped_file, '-o', output_vcf, '-q', '-n']
        print >> sys.stdout, 'VT Command: %s'%(' '.join(cmd))
        #logger.debug('VT Command: %s'%(' '.join(cmd)))
    elif method == 'bcf':
        cmd = [norm_command, 'norm', '-m', '-', '-O', 'b', '-o', output_vcf, zipped_file]
        print >> sys.stdout, 'bcftools norm Command: %s'%(' '.join(cmd))
        #logger.info('bcftools norm Command: %s'%(' '.join(cmd)))
    try:
        rv = subprocess.check_call(cmd)
        fix_contig_tag_in_vcf_by_line(output_vcf)
        #fix_contig_tag_in_vcf(output_vcf)
        return output_vcf
    except subprocess.CalledProcessError, e:
        print >> sys.stderr, "Non-zero exit code from normalization! Bailing out."
        #logger.critical("Non-zero exit code from normalization! Bailing out.")
        sys.exit(1)


